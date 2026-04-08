from troposphere import Ref
from troposphere.ec2 import SecurityGroup, SecurityGroupRule

from .ecs import C4ECSApplication
from .network import C4Network, C4NetworkExports
from .scre_network import C4SCRENetworkExports
from ..base import ConfigManager
from ..constants import Settings


class C4SCREECSApplication(C4ECSApplication):
    """
    SCRE variant of C4ECSApplication. Creates the ECS cluster, services, load balancer,
    and supporting resources inside an IT-provided VPC.

    Two changes from the base class:
    1. NETWORK_EXPORTS is swapped to C4SCRENetworkExports so VPC/subnet cross-stack
       references resolve against the SCRE network stack outputs.
    2. ecs_container_security_group() is overridden to use a config-driven VPC CIDR
       (vpc.cidr) instead of the hardcoded C4Network.CIDR_BLOCK ('10.0.0.0/16').

    All other ECS resources (cluster, tasks, services, load balancer, alarms) are
    inherited unchanged.
    """
    NETWORK_EXPORTS = C4SCRENetworkExports()

    STACK_NAME_TOKEN = 'scre-ecs'
    STACK_TITLE_TOKEN = 'SCREEcs'

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
