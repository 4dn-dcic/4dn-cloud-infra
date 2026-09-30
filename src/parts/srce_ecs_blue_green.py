from .ecs_blue_green import ECSBlueGreen
from .srce_network import SRCENetworkMixin


class SRCEECSBlueGreen(SRCENetworkMixin, ECSBlueGreen):
    """
    SRCE variant of ECSBlueGreen. Deploys a blue/green ECS configuration inside an
    IT-provided VPC.

    The SRCE-specific wiring (NETWORK_EXPORTS routed to the SRCE network stack and a
    config-driven container security group CIDR) lives in SRCENetworkMixin, shared with
    C4SRCEECSApplication. All blue/green cluster, task, service, load balancer, and alarm
    logic is inherited from ECSBlueGreen unchanged.
    """
    STACK_NAME_TOKEN = 'srce-ecs-blue-green'
    STACK_TITLE_TOKEN = 'SRCEEcsBlueGreen'
