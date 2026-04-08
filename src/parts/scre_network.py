import re

from troposphere import Template, Output, Parameter as CFNParameter, Ref

from .network import C4Network, C4NetworkExports
from ..constants import Settings
from ..base import ConfigManager
from ..exports import C4Exports, exportify
from ..part import C4Part


class C4SCRENetworkExports(C4Exports):
    """
    Helper class for working with network exported resources in the SCRE
    (Secure Research Collaborative Environment) setup, where the VPC and subnets
    are IT-provided and are not created by this stack.
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
        """Read IT-provided private subnet IDs from config rather than scanning stack outputs."""
        subnet_ids = ConfigManager.get_config_setting(Settings.PRIVATE_SUBNETS, default=None)
        if not subnet_ids:
            raise RuntimeError(
                "get_subnet_ids() requires 'private.subnets' to be set in config.json for SCRE deployments."
            )
        if isinstance(subnet_ids, str):
            subnet_ids = [s.strip() for s in subnet_ids.split(',')]
        return subnet_ids

    def __init__(self):
        parameter = 'NetworkStackNameParameter'
        super().__init__(parameter)


class C4SCRENetwork(C4Network, C4Part):
    """
    SCRE variant of C4Network. IT provides the VPC, subnets, and routing infrastructure.
    This stack only creates security groups and exports the pre-existing VPC and subnet IDs
    so downstream stacks (datastore, ECS) can import them using the standard cross-stack
    reference pattern — identical to a normal network stack from the consumer's perspective.
    """

    DB_PORT_LOW = 5400
    DB_PORT_HIGH = 5499
    EXPORTS = C4SCRENetworkExports()
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
