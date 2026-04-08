from troposphere import Ref
from troposphere.ec2 import SecurityGroup, SecurityGroupRule

from .ecs_blue_green import ECSBlueGreen
from .network import C4Network, C4NetworkExports
from .scre_network import C4SCRENetworkExports
from ..base import ConfigManager
from ..constants import Settings


class SCREECSBlueGreen(ECSBlueGreen):
    """
    SCRE variant of ECSBlueGreen. Deploys a blue/green ECS configuration inside an
    IT-provided VPC by swapping in C4SCRENetworkExports so all VPC/subnet cross-stack
    references resolve against the SCRE network stack outputs.

    ecs_container_security_group() is overridden to use a config-driven VPC CIDR
    (vpc.cidr) instead of the hardcoded C4Network.CIDR_BLOCK.

    All blue/green cluster, task, service, load balancer, and alarm logic is inherited
    from ECSBlueGreen unchanged.
    """
    NETWORK_EXPORTS = C4SCRENetworkExports()

    STACK_NAME_TOKEN = 'scre-ecs-blue-green'
    STACK_TITLE_TOKEN = 'SCREEcsBlueGreen'

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
