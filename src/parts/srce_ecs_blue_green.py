from troposphere.ec2 import SecurityGroup

from ..base import ConfigManager
from ..constants import Settings
from .ecs_blue_green import ECSBlueGreen
from .network import C4NetworkExports
from .srce_network import SRCENetworkMixin


class SRCEECSBlueGreen(SRCENetworkMixin, ECSBlueGreen):
    """
    SRCE variant of ECSBlueGreen. Deploys a blue/green ECS configuration inside an
    IT-provided VPC.

    The SRCE-specific wiring (NETWORK_EXPORTS routed to the SRCE network stack and a
    config-driven container security group CIDR) lives in SRCENetworkMixin, shared with
    C4SRCEECSApplication. All blue/green cluster, task, service, load balancer, and alarm
    logic is inherited from ECSBlueGreen unchanged, except for the opt-in closed bootstrap
    stage (ecs.bootstrap_closed) below.
    """
    STACK_NAME_TOKEN = 'srce-ecs-blue-green'
    STACK_TITLE_TOKEN = 'SRCEEcsBlueGreen'

    def bootstrap_closed(self) -> bool:
        """ ecs.bootstrap_closed, parsed strictly: unset or false -> the normal stack; true -> the
            closed bootstrap stage. Any other value raises rather than silently emitting the open
            normal stack because of a typo. """
        value = ConfigManager.get_config_setting(Settings.ECS_BOOTSTRAP_CLOSED, default=None)
        if value is None or isinstance(value, bool):
            return bool(value)
        raise ValueError(f'{Settings.ECS_BOOTSTRAP_CLOSED} must be true or false, not {value!r}')

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ In the closed bootstrap stage the (permanent) ALB security group keeps its logical id,
            description and VPC but has no ingress rule; leaving the stage restores the normal
            80/443 ingress as an in-place update. """
        if not self.bootstrap_closed():
            return super().ecs_lb_security_group()
        return SecurityGroup(
            self.name.logical_id('LBSecurityGroup'),
            GroupDescription="Web load balancer security group.",
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array()
        )
