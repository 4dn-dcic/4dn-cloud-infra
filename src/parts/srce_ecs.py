from .ecs import C4ECSApplication
from .srce_network import SRCENetworkMixin


class C4SRCEECSApplication(SRCENetworkMixin, C4ECSApplication):
    """
    SRCE variant of C4ECSApplication. Creates the ECS cluster, services, load balancer,
    and supporting resources inside an IT-provided VPC.

    The SRCE-specific wiring (NETWORK_EXPORTS routed to the SRCE network stack and a
    config-driven container security group CIDR) lives in SRCENetworkMixin, shared with
    SRCEECSBlueGreen. All other ECS resources (cluster, tasks, services, load balancer,
    alarms) are inherited unchanged.
    """
    STACK_NAME_TOKEN = 'srce-ecs'
    STACK_TITLE_TOKEN = 'SRCEEcs'
