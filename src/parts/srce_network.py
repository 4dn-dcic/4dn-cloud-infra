import re

from troposphere import Template, Output, Parameter as CFNParameter, Ref

from .network import C4Network, C4NetworkExports
from ..constants import Settings
from ..base import ConfigManager
from ..exports import C4Exports, exportify
from ..part import C4Part


class C4SRCENetworkExports(C4Exports):
    """
    Exports for the SRCE Application VPC (ECS portal + foursight).

    References the 'srce-network' CloudFormation stack via NetworkStackNameParameter.
    Subnet IDs are read from 'private.subnets' / 'public.subnets' in config.json.
    """
    VPC = 'VPC'

    APPLICATION_SECURITY_GROUP = exportify('ApplicationSecurityGroup')
    DB_SECURITY_GROUP = exportify('DBSecurityGroup')
    HTTPS_SECURITY_GROUP = exportify('HTTPSSecurityGroup')

    _APPLICATION_SECURITY_GROUP_EXPORT_PATTERN = re.compile('.*Network.*ApplicationSecurityGroup.*')

    @classmethod
    def get_security_ids(cls):
        computed_result = ConfigManager.find_stack_outputs(cls._APPLICATION_SECURITY_GROUP_EXPORT_PATTERN.match,
                                                           value_only=True)
        return computed_result

    _PRIVATE_SUBNET_EXPORT_PATTERN = re.compile('.*Network.*PrivateSubnet.*')

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Application VPC private subnet IDs from config."""
        subnet_ids = ConfigManager.get_config_setting(Settings.PRIVATE_SUBNETS, default=None)
        if not subnet_ids:
            raise RuntimeError(
                "get_subnet_ids() requires 'private.subnets' to be set in config.json for SRCE deployments."
            )
        if isinstance(subnet_ids, str):
            subnet_ids = [s.strip() for s in subnet_ids.split(',')]
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
    PRIVATE_SUBNETS = C4NetworkExports.PRIVATE_SUBNETS
    PUBLIC_SUBNETS = C4NetworkExports.PUBLIC_SUBNETS

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Database VPC private subnet IDs from config."""
        subnet_ids = ConfigManager.get_config_setting(Settings.DB_PRIVATE_SUBNETS, default=None)
        if not subnet_ids:
            raise RuntimeError(
                "get_subnet_ids() requires 'db.private.subnets' to be set in config.json for SRCE deployments."
            )
        if isinstance(subnet_ids, str):
            subnet_ids = [s.strip() for s in subnet_ids.split(',')]
        return subnet_ids

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
    PUBLIC_SUBNETS = C4NetworkExports.PUBLIC_SUBNETS

    @classmethod
    def get_subnet_ids(cls):
        """Read IT-provided Compute VPC private subnet IDs from config."""
        subnet_ids = ConfigManager.get_config_setting(Settings.COMPUTE_PRIVATE_SUBNETS, default=None)
        if not subnet_ids:
            raise RuntimeError(
                "get_subnet_ids() requires 'compute.private.subnets' to be set in config.json for SRCE deployments."
            )
        if isinstance(subnet_ids, str):
            subnet_ids = [s.strip() for s in subnet_ids.split(',')]
        return subnet_ids

    def __init__(self):
        super().__init__('ComputeNetworkStackNameParameter')


class C4SRCENetwork(C4Network, C4Part):
    """
    SRCE variant of C4Network. IT provides the VPC, subnets, and routing infrastructure.
    This stack only creates security groups and exports the pre-existing VPC and subnet IDs
    so downstream stacks (datastore, ECS) can import them using the standard cross-stack
    reference pattern — identical to a normal network stack from the consumer's perspective.
    """

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

    def _subnet_outputs(self) -> list:
        """
        Export IT-provided subnet IDs as CloudFormation outputs using the same export
        names as a normal Network stack (PrivateSubnetA, PublicSubnetA, etc.).
        Downstream stacks import these via ImportValue without any modification.
        """
        outputs = []

        private_subnet_ids = ConfigManager.get_config_setting(Settings.PRIVATE_SUBNETS, default=[])
        if isinstance(private_subnet_ids, str):
            private_subnet_ids = [s.strip() for s in private_subnet_ids.split(',')]
        for i, subnet_id in enumerate(private_subnet_ids):
            if i >= len(C4NetworkExports.PRIVATE_SUBNETS):
                break
            export_name = C4NetworkExports.PRIVATE_SUBNETS[i]
            logical_id = self.name.logical_id(export_name)
            outputs.append(Output(
                logical_id,
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))

        public_subnet_ids = ConfigManager.get_config_setting(Settings.PUBLIC_SUBNETS, default=[])
        if isinstance(public_subnet_ids, str):
            public_subnet_ids = [s.strip() for s in public_subnet_ids.split(',')]
        for i, subnet_id in enumerate(public_subnet_ids):
            if i >= len(C4NetworkExports.PUBLIC_SUBNETS):
                break
            export_name = C4NetworkExports.PUBLIC_SUBNETS[i]
            logical_id = self.name.logical_id(export_name)
            outputs.append(Output(
                logical_id,
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))

        return outputs

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

    def virtual_private_cloud(self):
        return CFNParameter(
            'ExistingDBVPCId',
            Description='ID of IT-provided Database VPC (configure via db.vpc.id in config.json)',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.DB_VPC_ID, default=''),
        )

    def _subnet_outputs(self) -> list:
        """Export Database VPC private subnet IDs using standard PrivateSubnetA/B/... export names."""
        outputs = []
        subnet_ids = ConfigManager.get_config_setting(Settings.DB_PRIVATE_SUBNETS, default=[])
        if isinstance(subnet_ids, str):
            subnet_ids = [s.strip() for s in subnet_ids.split(',')]
        for i, subnet_id in enumerate(subnet_ids):
            if i >= len(C4NetworkExports.PRIVATE_SUBNETS):
                break
            export_name = C4NetworkExports.PRIVATE_SUBNETS[i]
            logical_id = self.name.logical_id(export_name)
            outputs.append(Output(
                logical_id,
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))
        return outputs


class C4SRCEComputeNetwork(C4SRCENetwork):
    """
    SRCE Network stack for the Compute VPC (Sentieon, JupyterHub, Higlass).

    Creates application security group(s) inside the IT-provided Compute VPC specified
    by 'compute.vpc.id' in config.json.  Exports use standard key names so that
    C4SRCESentieonSupport and other EC2 compute modules resolve imports correctly via
    ComputeNetworkStackNameParameter.
    """
    STACK_NAME_TOKEN = 'srce-network-compute'
    STACK_TITLE_TOKEN = 'SRCENetworkCompute'
    EXPORTS = C4SRCEComputeNetworkExports()

    @property
    def CIDR_BLOCK(self):
        return ConfigManager.get_config_setting(Settings.COMPUTE_VPC_CIDR, default=C4Network.CIDR_BLOCK)

    def virtual_private_cloud(self):
        return CFNParameter(
            'ExistingComputeVPCId',
            Description='ID of IT-provided Compute VPC (configure via compute.vpc.id in config.json)',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.COMPUTE_VPC_ID, default=''),
        )

    def _subnet_outputs(self) -> list:
        """Export Compute VPC private and public subnet IDs using standard export names."""
        outputs = []
        private_ids = ConfigManager.get_config_setting(Settings.COMPUTE_PRIVATE_SUBNETS, default=[])
        if isinstance(private_ids, str):
            private_ids = [s.strip() for s in private_ids.split(',')]
        for i, subnet_id in enumerate(private_ids):
            if i >= len(C4NetworkExports.PRIVATE_SUBNETS):
                break
            export_name = C4NetworkExports.PRIVATE_SUBNETS[i]
            logical_id = self.name.logical_id(export_name)
            outputs.append(Output(
                logical_id,
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))
        public_ids = ConfigManager.get_config_setting(Settings.COMPUTE_PUBLIC_SUBNETS, default=[])
        if isinstance(public_ids, str):
            public_ids = [s.strip() for s in public_ids.split(',')]
        for i, subnet_id in enumerate(public_ids):
            if i >= len(C4NetworkExports.PUBLIC_SUBNETS):
                break
            export_name = C4NetworkExports.PUBLIC_SUBNETS[i]
            logical_id = self.name.logical_id(export_name)
            outputs.append(Output(
                logical_id,
                Value=subnet_id,
                Export=self.EXPORTS.export(export_name),
            ))
        return outputs
