from troposphere.ec2 import SecurityGroup

from ..base import ConfigManager
from ..constants import Settings
from .ecs_blue_green import ApplicationTypes, ECSBlueGreen
from .network import C4NetworkExports
from .srce_backend_tls import SRCEBackendTLSMixin
from .srce_network import SRCENetworkMixin
from .srce_observability import SRCEObservabilityMixin


class SRCEECSBlueGreen(SRCEObservabilityMixin, SRCEBackendTLSMixin, SRCENetworkMixin, ECSBlueGreen):
    """
    SRCE variant of ECSBlueGreen. Deploys a blue/green ECS configuration inside an
    IT-provided VPC.

    The SRCE-specific wiring (NETWORK_EXPORTS routed to the SRCE network stack and a
    config-driven container security group CIDR) lives in SRCENetworkMixin, shared with
    C4SRCEECSApplication. All blue/green cluster, task, service, load balancer, and alarm
    logic is inherited from ECSBlueGreen unchanged, except for the opt-in closed bootstrap
    stage (ecs.bootstrap_closed) below, the opt-in backend TLS of SRCEBackendTLSMixin and the opt-in
    Falcon/Splunk sidecars of SRCEObservabilityMixin.
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

    def ecs_indexer_task(self, cpu='256', memory='512', **kwargs):
        """ ECSBlueGreen pins the indexer at 256/512 and ignores ecs.indexer.cpu/memory. Once the indexer
            carries the observability sidecars (FireLens alone reserves 256 MiB) honour those settings, as
            the standalone stack and the blue/green ingester already do; their defaults are the same
            256/512, and with the sidecars off the render is unchanged. """
        if self.observes(ApplicationTypes.INDEXER):
            cpu = memory = None
        return super().ecs_indexer_task(cpu=cpu, memory=memory, **kwargs)
