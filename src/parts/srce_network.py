import json

from troposphere import Template, Output, Parameter as CFNParameter, Ref
from troposphere.ec2 import SecurityGroupIngress, SecurityGroupEgress, SecurityGroup, SecurityGroupRule

from .network import C4Network, C4NetworkExports
from ..constants import Settings
from ..base import ConfigManager
from ..exports import C4Exports, exportify
from ..part import C4Part


def _parse_subnet_ids(value):
    """
    Parse subnet IDs from a config value that may be:
    - already a list: ["subnet-abc", "subnet-def"]
    - a Python-repr / JSON array string: "['subnet-abc', 'subnet-def']"
    - a comma-separated string: "subnet-abc, subnet-def"  (the documented, preferred form)

    The Python-repr string case exists because ConfigManager._load_config stringifies all config
    values so they can be sourced into os.environ (which only holds strings); a JSON list in
    config.json therefore arrives here as its Python repr. See the CLN-10 note in src/base.py.
    Returns a list of clean subnet ID strings.
    """
    if isinstance(value, list):
        return [s.strip() for s in value]
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith('['):
            try:
                # Handle proper JSON arrays
                return [s.strip() for s in json.loads(stripped)]
            except json.JSONDecodeError:
                # Handle Python list repr: "['subnet-abc', 'subnet-def']"
                inner = stripped[1:-1]
                return [s.strip().strip("'\"") for s in inner.split(',') if s.strip()]
        return [s.strip() for s in stripped.split(',') if s.strip()]
    return []


def _read_subnet_ids(setting_key):
    """ Shared helper for the SRCE *NetworkExports.get_subnet_ids() classmethods: read the
        IT-provided subnet IDs for the given config key, raising a clear error if unset. """
    subnet_ids = _parse_subnet_ids(ConfigManager.get_config_setting(setting_key, default=None))
    if not subnet_ids:
        raise RuntimeError(
            f"get_subnet_ids() requires {setting_key!r} to be set in config.json for SRCE deployments."
        )
    return subnet_ids


def _required_subnet_export_names(setting_key, export_names, label):
    """ The subnet export names an SRCE stack may reference, one per IT-provided subnet.

        Raises rather than returning an empty list when the config key is unset: see the note on
        C4SRCENetworkExports.PRIVATE_SUBNETS. Also refuses to name more subnets than
        C4NetworkExports declares, since a name beyond that list has no matching export.
    """
    subnet_ids = _read_subnet_ids(setting_key)
    if len(subnet_ids) > len(export_names):
        raise RuntimeError(
            f"{setting_key!r} lists {len(subnet_ids)} {label} subnets but only"
            f" {len(export_names)} subnet exports exist ({list(export_names)}); the extra subnets"
            f" could not be exported or imported."
        )
    return export_names[:len(subnet_ids)]


def _assert_no_other_vpc_subnets(subnet_ids):
    """ Guard for the SRCE three-VPC split: the Application VPC's private subnets must not overlap
        the Database or Compute VPC's. Anything attached to those subnets (Foursight Lambda ENIs,
        ECS task ENIs) is required to sit in exactly one VPC, and a subnet ID that appears under
        two of the three config keys means the VPC boundaries in config.json are wrong. Fail here,
        at synthesis/package time, rather than at CloudFormation time. """
    subnet_ids = set(subnet_ids)
    for setting_key, vpc_label in ((Settings.DB_PRIVATE_SUBNETS, 'Database'),
                                   (Settings.COMPUTE_PRIVATE_SUBNETS, 'Compute')):
        other = set(_parse_subnet_ids(ConfigManager.get_config_setting(setting_key, default=[])))
        overlap = sorted(other & subnet_ids)
        if overlap:
            raise RuntimeError(
                f"{Settings.PRIVATE_SUBNETS!r} (Application VPC) and {setting_key!r}"
                f" ({vpc_label} VPC) both list {overlap}. Application VPC subnets must be"
                f" disjoint from the other SRCE VPCs' subnets."
            )


class C4SRCENetworkExports(C4Exports):
    """
    Exports for the SRCE Application VPC (ECS portal + foursight).

    References the 'srce-network' CloudFormation stack via NetworkStackNameParameter.
    Subnet IDs are read from 'private.subnets' / 'public.subnets' in config.json.

    PRIVATE_SUBNETS and PUBLIC_SUBNETS are sized to match the configured subnets
    so that downstream stacks (ECS, etc.) only reference exports that actually exist.
    """
    VPC = 'VPC'

    APPLICATION_SECURITY_GROUP = exportify('ApplicationSecurityGroup')
    DB_SECURITY_GROUP = exportify('DBSecurityGroup')
    HTTPS_SECURITY_GROUP = exportify('HTTPSSecurityGroup')

    # Subnet export names, limited to the number of IT-provided subnets in config, using the same
    # PrivateSubnetA/B/... naming as C4NetworkExports. Exposed as lazy properties (not class
    # attributes) so the config read happens at access time rather than at module-import time —
    # alpha_stacks imports this unconditionally on every CLI invocation (CLN-9).
    #
    # Both fail loudly on an unset/empty config key rather than returning []. An empty list is
    # never a usable answer here: it would emit an ECS service with no Subnets and a Foursight
    # VpcConfig with none either, which CloudFormation accepts as "no networking" or (for chalice,
    # whose build_config() gates on `if subnet_ids:`) silently leaves a stale config in place.
    @property
    def PRIVATE_SUBNETS(self):
        return _required_subnet_export_names(Settings.PRIVATE_SUBNETS,
                                             C4NetworkExports.PRIVATE_SUBNETS,
                                             'Application VPC private')

    @property
    def PUBLIC_SUBNETS(self):
        return _required_subnet_export_names(Settings.PUBLIC_SUBNETS,
                                             C4NetworkExports.PUBLIC_SUBNETS,
                                             'Application VPC public')

    @classmethod
    def get_security_ids(cls):
        """
        Resolve the Application VPC security group that Foursight Lambdas attach to.

        Foursight is packaged by chalice, which cannot use ImportValue: it needs *literal*
        security-group IDs written into .chalice/config.json before anything is deployed. It
        therefore has to look the value up itself, and the identifier it looks it up by is the
        whole problem.

        The inherited C4NetworkExports implementation scanned every stack in the account for an
        output *key* matching '.*Network.*ApplicationSecurityGroup.*'. That is unambiguous in a
        normal deployment (only c4-network-main-stack matches) but wrong for SRCE: all three SRCE
        network stacks create an ApplicationSecurityGroup in their *own* VPC and export it under
        that same loose pattern, so the Lambdas were handed three security groups from three
        different VPCs and CloudFormation rejected each one with
        "Security Groups are required to be in the same VPC".

        Match the CloudFormation **export name** instead -- the exact identifier the SRCE ECS
        stacks already resolve with Fn::ImportValue via NetworkStackNameParameter:

            c4-srce-network-main-stack-ApplicationSecurityGroup

        That is what C4Exports.export() writes at synthesis time and what C4Exports.import_value()
        reads, so Foursight and ECS now agree by construction. It also decouples the lookup from
        the template's logical-id naming (title token + camelized sharing qualifier), which is a
        second, independent identifier for the same output that a renamed or re-tokenized stack
        can change without the export name changing.

        A stack whose outputs carry the key but no export name is still accepted, via that exact
        output key. Both lookups name a single stack, so neither reintroduces the cross-VPC
        ambiguity that the loose pattern had.
        """
        export_name = cls.application_security_group_export_name()
        computed_result = ConfigManager.find_stack_exports(export_name, value_only=True)
        if computed_result:
            return computed_result

        output_key = cls.application_security_group_output_key()
        computed_result = ConfigManager.find_stack_outputs(output_key, value_only=True)
        if computed_result:
            return computed_result

        raise RuntimeError(
            f"get_security_ids() could not resolve the SRCE Application VPC security group."
            f" Looked for CloudFormation export {export_name!r} -- the same identifier"
            f" `cli provision srce-ecs` resolves with Fn::ImportValue -- and then for stack output"
            f" key {output_key!r}, and found neither in this account."
            f"{cls._describe_available_application_security_groups()}"
            f" Expected owner stack: {C4SRCENetwork.suggest_stack_name().stack_name}."
        )

    @classmethod
    def application_security_group_export_name(cls):
        """ The CloudFormation export name under which the SRCE *Application* network stack
            publishes its ApplicationSecurityGroup: '<stack name>-ApplicationSecurityGroup'.
            Built the same way C4Exports.export() builds it, from C4SRCENetwork's own stack name,
            so it cannot drift from what C4SRCENetwork.build_template() emits. """
        return f'{C4SRCENetwork.suggest_stack_name().stack_name}-{cls.APPLICATION_SECURITY_GROUP}'

    @classmethod
    def application_security_group_output_key(cls):
        """ The CloudFormation output key (template logical id) for that same output, e.g.
            'C4SRCENetworkMainApplicationSecurityGroup'. Fallback only -- see get_security_ids(). """
        return C4SRCENetwork.suggest_stack_name().logical_id(cls.APPLICATION_SECURITY_GROUP)

    @classmethod
    def _describe_available_application_security_groups(cls):
        """ Diagnostic for the get_security_ids() failure message: which ApplicationSecurityGroup
            exports *do* exist in this account. Names only -- never values -- so it is safe to
            print. Best effort: a failure here must not mask the original error. """
        try:
            found = ConfigManager.find_stack_exports(
                lambda name: bool(name) and name.endswith(cls.APPLICATION_SECURITY_GROUP))
        except Exception:  # pragma: no cover - diagnostics must never raise
            return ''
        if not found:
            return (' No stack in this account exports an ApplicationSecurityGroup at all,'
                    ' which suggests the SRCE Application network stack is not deployed.')
        return f' ApplicationSecurityGroup exports that do exist: {sorted(found)}.'

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Application VPC private subnet IDs from config.

        Also refuses subnets that are shared with the Database or Compute VPC: a Lambda (or ECS
        task) ENI must land in the Application VPC only, and a subnet listed under two VPCs is the
        same mixed-VPC mistake as the security-group case above, just via config rather than
        cross-stack discovery.
        """
        subnet_ids = _read_subnet_ids(Settings.PRIVATE_SUBNETS)
        _assert_no_other_vpc_subnets(subnet_ids)
        return subnet_ids

    def __init__(self):
        super().__init__('NetworkStackNameParameter')


class C4SRCEDBNetworkExports(C4Exports):
    """
    Exports for the SRCE Database VPC (RDS, OpenSearch, Redis).

    References the 'srce-network-db' CloudFormation stack via DBNetworkStackNameParameter.
    Export key names (VPC, PrivateSubnetA, DBSecurityGroup, etc.) are identical to those
    used by the regular network stack so that C4Datastore and C4Redis can be inherited
    unchanged — the different reference_param_key routes imports to the correct stack.
    Subnet IDs are read from 'db.private.subnets' in config.json.
    """
    VPC = C4NetworkExports.VPC
    DB_SECURITY_GROUP = C4NetworkExports.DB_SECURITY_GROUP
    HTTPS_SECURITY_GROUP = C4NetworkExports.HTTPS_SECURITY_GROUP
    APPLICATION_SECURITY_GROUP = C4NetworkExports.APPLICATION_SECURITY_GROUP
    # NOTE: unlike C4SRCENetworkExports, this is NOT truncated to the configured subnet count.
    # C4Datastore instead truncates by subnet.pair_count (default 2) when building the RDS subnet
    # group, so an SRCE DB VPC must either have exactly 2 private subnets or set subnet.pair_count
    # to match db.private.subnets, otherwise the RDS subnet group would ImportValue exports that do
    # not exist (CLN-9).
    PRIVATE_SUBNETS = C4NetworkExports.PRIVATE_SUBNETS

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Database VPC private subnet IDs from config."""
        return _read_subnet_ids(Settings.DB_PRIVATE_SUBNETS)

    def __init__(self):
        super().__init__('DBNetworkStackNameParameter')


class C4SRCEComputeNetworkExports(C4Exports):
    """
    Exports for the SRCE Compute VPC (Sentieon, JupyterHub, Higlass).

    References the 'srce-network-compute' CloudFormation stack via ComputeNetworkStackNameParameter.
    Export key names match the standard network stack so inherited EC2 modules work unchanged.
    Subnet IDs are read from 'compute.private.subnets' in config.json.
    """
    VPC = C4NetworkExports.VPC
    APPLICATION_SECURITY_GROUP = C4NetworkExports.APPLICATION_SECURITY_GROUP
    PRIVATE_SUBNETS = C4NetworkExports.PRIVATE_SUBNETS

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Compute VPC private subnet IDs from config."""
        return _read_subnet_ids(Settings.COMPUTE_PRIVATE_SUBNETS)

    def __init__(self):
        super().__init__('ComputeNetworkStackNameParameter')


class SRCENetworkMixin:
    """
    Shared SRCE wiring for ECS parts (RED-2). Routes VPC/subnet cross-stack references to the SRCE
    Application network stack and overrides the container security group to use the config-driven
    VPC CIDR (vpc.cidr) instead of the hardcoded C4Network.CIDR_BLOCK. Inherited (first, so it
    wins the MRO) by both C4SRCEECSApplication and SRCEECSBlueGreen, which previously carried
    byte-identical copies of NETWORK_EXPORTS and ecs_container_security_group().
    """
    NETWORK_EXPORTS = C4SRCENetworkExports()

    def ecs_container_security_group(self) -> SecurityGroup:
        """Security group for the container runtime, using config-provided VPC CIDR."""
        cidr = ConfigManager.get_config_setting(Settings.VPC_CIDR, default=C4Network.CIDR_BLOCK)
        logical_id = self.name.logical_id('ContainerSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupDescription='Container Security Group.',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp=cidr,
                )
            ],
            Tags=self.tags.cost_tag_array()
        )


class C4SRCENetwork(C4Network, C4Part):
    """
    SRCE variant of C4Network. IT provides the VPC, subnets, and routing infrastructure.
    This stack only creates security groups and exports the pre-existing VPC and subnet IDs
    so downstream stacks (datastore, ECS) can import them using the standard cross-stack
    reference pattern — identical to a normal network stack from the consumer's perspective.
    """

    # Override the network tokens inherited from C4NetworkBase ('network'/'Network') so this
    # stack does NOT collide with the standard network stack's CloudFormation name
    # (c4-network-main-stack). Without this, deploying srce-network would target the same stack
    # as the standard network stack and replace its real VPC/subnet/NAT resources (SEC-2). The
    # DB and Compute siblings already set their own tokens; the App VPC stack was missing them.
    STACK_NAME_TOKEN = 'srce-network'
    STACK_TITLE_TOKEN = 'SRCENetwork'

    DB_PORT_LOW = 5400
    DB_PORT_HIGH = 5499
    EXPORTS = C4SRCENetworkExports()
    SHARING = 'ecosystem'

    @property
    def CIDR_BLOCK(self):
        """Use config-provided VPC CIDR (falls back to C4Network default if not set)."""
        return ConfigManager.get_config_setting(Settings.VPC_CIDR, default=C4Network.CIDR_BLOCK)

    def virtual_private_cloud(self):
        """
        Returns a CloudFormation Parameter referencing the IT-provided VPC ID.
        Ref(parameter) returns the VPC ID string at deploy time.
        Security group methods inherited from C4Network call Ref(self.virtual_private_cloud()),
        which correctly resolves to the existing VPC ID via this parameter.
        """
        return CFNParameter(
            'ExistingVPCId',
            Description='ID of IT-provided VPC (configure via vpc.id in config.json)',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.VPC_ID, default=''),
        )

    def output_virtual_private_cloud(self) -> Output:
        """Export the IT-provided VPC ID so downstream stacks can ImportValue it."""
        export_name = C4NetworkExports.VPC
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(self.virtual_private_cloud()),
            Export=self.EXPORTS.export(export_name),
        )

    def _subnet_outputs_for(self, setting_key, export_names) -> list:
        """
        Shared helper: export IT-provided subnet IDs (read from the given config key) as
        CloudFormation outputs using the given standard export names (PrivateSubnetA/B/...,
        PublicSubnetA/B/...). Downstream stacks import these via ImportValue unchanged. Used by
        all three SRCE network classes (App/DB/Compute), which differ only in the config key and
        export-name family (RED-3).
        """
        outputs = []
        subnet_ids = _parse_subnet_ids(ConfigManager.get_config_setting(setting_key, default=[]))
        for i, subnet_id in enumerate(subnet_ids):
            if i >= len(export_names):
                break
            export_name = export_names[i]
            outputs.append(Output(
                self.name.logical_id(export_name),
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))
        return outputs

    def _subnet_outputs(self) -> list:
        """ Application VPC exports both private and public subnets. """
        return (self._subnet_outputs_for(Settings.PRIVATE_SUBNETS, C4NetworkExports.PRIVATE_SUBNETS) +
                self._subnet_outputs_for(Settings.PUBLIC_SUBNETS, C4NetworkExports.PUBLIC_SUBNETS))

    def cross_vpc_security_rules(self):
        """
        Additional security group rules for cross-VPC traffic.
        The App VPC needs to reach the DB VPC (RDS, OpenSearch, Redis)
        and the Compute VPC (Sentieon, JupyterHub, Higlass), and vice versa.
        """
        rules = []
        db_cidr = ConfigManager.get_config_setting(Settings.DB_VPC_CIDR, default=None)
        compute_cidr = ConfigManager.get_config_setting(Settings.COMPUTE_VPC_CIDR, default=None)

        if db_cidr:
            # App -> DB VPC: allow DB port range (RDS)
            rules.append(SecurityGroupIngress(
                self.name.logical_id('DBPortRangeFromDBVPC', context='cross_vpc_db_in'),
                CidrIp=db_cidr,
                Description='allows DB port access from Database VPC',
                GroupId=Ref(self.db_security_group()),
                IpProtocol='tcp',
                FromPort=self.DB_PORT_LOW,
                ToPort=self.DB_PORT_HIGH,
            ))
            rules.append(SecurityGroupEgress(
                self.name.logical_id('DBPortRangeToDBVPC', context='cross_vpc_db_out'),
                CidrIp=db_cidr,
                Description='allows DB port access to Database VPC',
                GroupId=Ref(self.db_security_group()),
                IpProtocol='tcp',
                FromPort=self.DB_PORT_LOW,
                ToPort=self.DB_PORT_HIGH,
            ))
            # App -> DB VPC: allow Redis (6379)
            rules.append(SecurityGroupIngress(
                self.name.logical_id('RedisFromDBVPC', context='cross_vpc_redis_in'),
                CidrIp=db_cidr,
                Description='allows Redis access from Database VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=6379,
                ToPort=6379,
            ))
            rules.append(SecurityGroupEgress(
                self.name.logical_id('RedisToDBVPC', context='cross_vpc_redis_out'),
                CidrIp=db_cidr,
                Description='allows Redis access to Database VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=6379,
                ToPort=6379,
            ))
            # App -> DB VPC: allow HTTPS (443) for OpenSearch
            rules.append(SecurityGroupEgress(
                self.name.logical_id('HTTPSToDBVPC', context='cross_vpc_https_db_out'),
                CidrIp=db_cidr,
                Description='allows HTTPS access to Database VPC (OpenSearch)',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))

        if compute_cidr:
            # App <-> Compute VPC: allow HTTPS (443)
            rules.append(SecurityGroupEgress(
                self.name.logical_id('HTTPSToComputeVPC', context='cross_vpc_https_compute_out'),
                CidrIp=compute_cidr,
                Description='allows HTTPS access to Compute VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))
            rules.append(SecurityGroupIngress(
                self.name.logical_id('HTTPSFromComputeVPC', context='cross_vpc_https_compute_in'),
                CidrIp=compute_cidr,
                Description='allows HTTPS access from Compute VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))
            # Compute VPC -> App VPC: allow Sentieon license server port (8990)
            # Sentieon runs in App VPC but compute jobs in the Compute VPC need to reach it
            rules.append(SecurityGroupIngress(
                self.name.logical_id('SentieonFromComputeVPC', context='cross_vpc_sentieon_in'),
                CidrIp=compute_cidr,
                Description='allows Sentieon license server access from Compute VPC (port 8990)',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=8990,
                ToPort=8990,
            ))

        return rules

    def build_template(self, template: Template) -> Template:
        # Add VPC parameter (IT-provided; not created here)
        template.add_parameter(self.virtual_private_cloud())

        # Export VPC ID so downstream stacks can use ImportValue
        template.add_output(self.output_virtual_private_cloud())

        # Export IT-provided subnet IDs so downstream stacks can import them
        for output in self._subnet_outputs():
            template.add_output(output)

        # Add security groups (created by this stack, inside the IT-provided VPC)
        for i in [self.db_security_group(), self.https_security_group(), self.application_security_group()]:
            template.add_resource(i)
        # Add security group outputs
        for i in [self.db_security_group_output(), self.https_security_group_output(),
                  self.application_security_group_output()]:
            template.add_output(i)

        # Add db inbound and outbound rules
        for i in [self.db_inbound_rule(), self.db_outbound_rule()]:
            template.add_resource(i)

        # Add https inbound and outbound rules
        for i in [self.https_inbound_rule(), self.https_outbound_rule()]:
            template.add_resource(i)

        # Add Application security rules
        for i in self.application_security_rules():
            template.add_resource(i)

        # Add cross-VPC security rules
        for i in self.cross_vpc_security_rules():
            template.add_resource(i)

        return template


class C4SRCEDBNetwork(C4SRCENetwork):
    """
    SRCE Network stack for the Database VPC (RDS, OpenSearch, Redis).

    Creates the same three security group types as C4SRCENetwork, but inside the
    IT-provided Database VPC specified by 'db.vpc.id' in config.json.  The export
    key names (VPC, PrivateSubnetA, DBSecurityGroup, …) are identical to those of a
    standard network stack so that C4SRCEDatastore and C4SRCERedis — which swap only
    their NETWORK_EXPORTS instance — resolve all cross-stack imports correctly via the
    DBNetworkStackNameParameter CloudFormation parameter.
    """
    STACK_NAME_TOKEN = 'srce-network-db'
    STACK_TITLE_TOKEN = 'SRCENetworkDB'
    EXPORTS = C4SRCEDBNetworkExports()

    @property
    def CIDR_BLOCK(self):
        return ConfigManager.get_config_setting(Settings.DB_VPC_CIDR, default=C4Network.CIDR_BLOCK)

    def cross_vpc_security_rules(self):
        """
        Cross-VPC rules for the Database VPC.
        The DB VPC must accept inbound connections from the App VPC for
        RDS (5400-5499), Redis (6379), and OpenSearch/HTTPS (443).
        """
        rules = []
        app_cidr = ConfigManager.get_config_setting(Settings.VPC_CIDR, default=None)
        if app_cidr:
            # App VPC -> DB: allow DB port range (RDS)
            rules.append(SecurityGroupIngress(
                self.name.logical_id('DBPortRangeFromAppVPC', context='cross_vpc_db_in'),
                CidrIp=app_cidr,
                Description='allows DB port access from Application VPC',
                GroupId=Ref(self.db_security_group()),
                IpProtocol='tcp',
                FromPort=self.DB_PORT_LOW,
                ToPort=self.DB_PORT_HIGH,
            ))
            rules.append(SecurityGroupEgress(
                self.name.logical_id('DBPortRangeToAppVPC', context='cross_vpc_db_out'),
                CidrIp=app_cidr,
                Description='allows DB port responses to Application VPC',
                GroupId=Ref(self.db_security_group()),
                IpProtocol='tcp',
                FromPort=self.DB_PORT_LOW,
                ToPort=self.DB_PORT_HIGH,
            ))
            # App VPC -> DB: allow Redis (6379)
            rules.append(SecurityGroupIngress(
                self.name.logical_id('RedisFromAppVPC', context='cross_vpc_redis_in'),
                CidrIp=app_cidr,
                Description='allows Redis access from Application VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=6379,
                ToPort=6379,
            ))
            rules.append(SecurityGroupEgress(
                self.name.logical_id('RedisToAppVPC', context='cross_vpc_redis_out'),
                CidrIp=app_cidr,
                Description='allows Redis responses to Application VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=6379,
                ToPort=6379,
            ))
            # App VPC -> DB: allow HTTPS (443) for OpenSearch
            rules.append(SecurityGroupIngress(
                self.name.logical_id('HTTPSFromAppVPC', context='cross_vpc_https_in'),
                CidrIp=app_cidr,
                Description='allows HTTPS access from Application VPC (OpenSearch)',
                GroupId=Ref(self.https_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))
        return rules

    def build_template(self, template: Template) -> Template:
        """DB VPC only needs the 3 SGs (for RDS, OpenSearch, Redis) and cross-VPC rules."""
        template.add_parameter(self.virtual_private_cloud())
        template.add_output(self.output_virtual_private_cloud())
        for output in self._subnet_outputs():
            template.add_output(output)
        for sg in [self.db_security_group(), self.https_security_group(), self.application_security_group()]:
            template.add_resource(sg)
        for sg_output in [self.db_security_group_output(), self.https_security_group_output(),
                          self.application_security_group_output()]:
            template.add_output(sg_output)
        for rule in self.cross_vpc_security_rules():
            template.add_resource(rule)
        return template

    def virtual_private_cloud(self):
        return CFNParameter(
            'ExistingDBVPCId',
            Description='ID of IT-provided Database VPC (configure via db.vpc.id in config.json)',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.DB_VPC_ID, default=''),
        )

    def _subnet_outputs(self) -> list:
        """Export Database VPC private subnet IDs using standard PrivateSubnetA/B/... export names."""
        return self._subnet_outputs_for(Settings.DB_PRIVATE_SUBNETS, C4NetworkExports.PRIVATE_SUBNETS)


class C4SRCEComputeNetwork(C4SRCENetwork):
    """
    SRCE Network stack for the Compute VPC (JupyterHub, Higlass).

    Creates application security group(s) inside the IT-provided Compute VPC specified
    by 'compute.vpc.id' in config.json.  Exports use standard key names so inherited
    EC2 compute modules resolve imports correctly via ComputeNetworkStackNameParameter.

    Note: Sentieon runs in the App VPC (needs public subnet), not here. Compute jobs
    reach the Sentieon license server cross-VPC on port 8990.
    """
    STACK_NAME_TOKEN = 'srce-network-compute'
    STACK_TITLE_TOKEN = 'SRCENetworkCompute'
    EXPORTS = C4SRCEComputeNetworkExports()

    @property
    def CIDR_BLOCK(self):
        return ConfigManager.get_config_setting(Settings.COMPUTE_VPC_CIDR, default=C4Network.CIDR_BLOCK)

    def cross_vpc_security_rules(self):
        """
        Cross-VPC rules for the Compute VPC.
        The Compute VPC must accept inbound connections from the App VPC
        on HTTPS (443) and SSH (22), and reach the Sentieon license server
        in the App VPC on port 8990.
        """
        rules = []
        app_cidr = ConfigManager.get_config_setting(Settings.VPC_CIDR, default=None)
        if app_cidr:
            rules.append(SecurityGroupIngress(
                self.name.logical_id('HTTPSFromAppVPC', context='cross_vpc_https_in'),
                CidrIp=app_cidr,
                Description='allows HTTPS access from Application VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))
            rules.append(SecurityGroupIngress(
                self.name.logical_id('SSHFromAppVPC', context='cross_vpc_ssh_in'),
                CidrIp=app_cidr,
                Description='allows SSH access from Application VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ))
            rules.append(SecurityGroupEgress(
                self.name.logical_id('HTTPSToAppVPC', context='cross_vpc_https_out'),
                CidrIp=app_cidr,
                Description='allows HTTPS responses to Application VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ))
            # Compute -> App VPC: Sentieon license server (8990)
            rules.append(SecurityGroupEgress(
                self.name.logical_id('SentieonToAppVPC', context='cross_vpc_sentieon_out'),
                CidrIp=app_cidr,
                Description='allows outbound to Sentieon license server in App VPC (port 8990)',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=8990,
                ToPort=8990,
            ))
        return rules

    def build_template(self, template: Template) -> Template:
        """Compute VPC only needs the Application SG (for JupyterHub, Higlass) and cross-VPC rules."""
        template.add_parameter(self.virtual_private_cloud())
        template.add_output(self.output_virtual_private_cloud())
        for output in self._subnet_outputs():
            template.add_output(output)
        template.add_resource(self.application_security_group())
        template.add_output(self.application_security_group_output())
        for rule in self.cross_vpc_security_rules():
            template.add_resource(rule)
        return template

    def virtual_private_cloud(self):
        return CFNParameter(
            'ExistingComputeVPCId',
            Description='ID of IT-provided Compute VPC (configure via compute.vpc.id in config.json)',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.COMPUTE_VPC_ID, default=''),
        )

    def _subnet_outputs(self) -> list:
        """Export Compute VPC private subnet IDs using standard export names."""
        return self._subnet_outputs_for(Settings.COMPUTE_PRIVATE_SUBNETS, C4NetworkExports.PRIVATE_SUBNETS)
