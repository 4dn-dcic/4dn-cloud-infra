import ipaddress
import re

from troposphere.ec2 import SecurityGroup, SecurityGroupRule

from ..base import ConfigManager
from ..constants import DeploymentParadigm, Settings
from ..foursight_api_policy import parse_source_cidrs
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
    stage (ecs.bootstrap_closed) and staging canary (ecs.staging_canary) below, the opt-in backend
    TLS of SRCEBackendTLSMixin and the opt-in Falcon/Splunk sidecars of SRCEObservabilityMixin.
    """
    STACK_NAME_TOKEN = 'srce-ecs-blue-green'
    STACK_TITLE_TOKEN = 'SRCEEcsBlueGreen'

    #: The colour the staging canary opens (blue serves staging); the other colour stays closed.
    STAGING_CANARY_COLOUR = DeploymentParadigm.BLUE
    #: Explicit service counts of the staging canary: the smallest that runs every service once.
    STAGING_CANARY_PORTAL_COUNT = 1
    STAGING_CANARY_INDEXER_COUNT = 1
    STAGING_CANARY_INGESTER_COUNT = 1
    #: Ports the canary admits from its source only (HTTPS, and the HTTP:80 -> HTTPS redirect).
    STAGING_CANARY_PORTS = (443, 80)
    _PREFIX_LIST_ID = re.compile(r'^pl-(?:[0-9a-f]{8}|[0-9a-f]{17})$')

    @staticmethod
    def _strict_bool(key) -> bool:
        """ A boolean setting parsed strictly: unset or false -> False, true -> True, anything else
            raises rather than silently selecting a different stage because of a typo. """
        value = ConfigManager.get_config_setting(key, default=None)
        if value is None or isinstance(value, bool):
            return bool(value)
        raise ValueError(f'{key} must be true or false, not {value!r}')

    def bootstrap_closed(self) -> bool:
        """ ecs.bootstrap_closed, parsed strictly: unset or false -> the normal stack; true -> the
            closed bootstrap stage. Any other value raises rather than silently emitting the open
            normal stack because of a typo. """
        return self._strict_bool(Settings.ECS_BOOTSTRAP_CLOSED)

    def staging_canary(self) -> bool:
        """ ecs.staging_canary, parsed strictly. True opens the staging colour only, admitted from the
            validated source alone (see staging_canary_source()); it is a partial opening, so it cannot
            be combined with the fully closed stage, and it needs an ALB certificate (it serves HTTPS).
            While it is off, a configured canary source is an error rather than silently ignored: the
            normal stack would admit 0.0.0.0/0 while the config reads as restricted. """
        enabled = self._strict_bool(Settings.ECS_STAGING_CANARY)
        if not enabled:
            stray = [key for key in (Settings.ECS_STAGING_CANARY_SOURCE_PREFIX_LIST,
                                     Settings.ECS_STAGING_CANARY_SOURCE_CIDRS)
                     if ConfigManager.get_config_setting(key, default=None) is not None]
            if stray:
                raise ValueError(f'{", ".join(stray)} only applies with {Settings.ECS_STAGING_CANARY}: true;'
                                 f' remove it, or enable the canary')
            return False
        if self.bootstrap_closed():
            raise ValueError(f'{Settings.ECS_STAGING_CANARY} and {Settings.ECS_BOOTSTRAP_CLOSED} are both true;'
                             f' the canary opens staging, so set {Settings.ECS_BOOTSTRAP_CLOSED} to false')
        if not self.lb_certificate_arn():
            raise ValueError(f'{Settings.ECS_STAGING_CANARY} serves HTTPS only and needs'
                             f' {Settings.ECS_LB_CERTIFICATE_ARN}')
        overridden = [key for key in (Settings.ECS_WSGI_COUNT, Settings.ECS_INDEXER_COUNT, Settings.ECS_INGESTER_COUNT)
                      if ConfigManager.get_config_setting(key, default=None) is not None]
        if overridden:
            raise ValueError(f'{Settings.ECS_STAGING_CANARY} uses fixed explicit service counts; remove'
                             f' {", ".join(overridden)}')
        self.staging_canary_source()  # validate now: a canary without a valid source never renders
        return True

    def staging_canary_source(self):
        """ The one ALB ingress source of the canary: ('prefix_list', 'pl-...') or ('cidrs', [...]).
            Exactly one of ecs.staging_canary_source_prefix_list / ecs.staging_canary_source_cidrs must be
            set. CIDRs must be public ranges (an internet-facing ALB sees the caller's public egress
            address) and never every address; a prefix list id must be well formed (its entries are
            managed by its owner, e.g. the institution's VPN egress list shared into the account). """
        prefix_list = ConfigManager.get_config_setting(Settings.ECS_STAGING_CANARY_SOURCE_PREFIX_LIST, default=None)
        cidrs = ConfigManager.get_config_setting(Settings.ECS_STAGING_CANARY_SOURCE_CIDRS, default=None)
        if (prefix_list is None) == (cidrs is None):
            raise ValueError(f'{Settings.ECS_STAGING_CANARY} needs exactly one source:'
                             f' {Settings.ECS_STAGING_CANARY_SOURCE_PREFIX_LIST} or'
                             f' {Settings.ECS_STAGING_CANARY_SOURCE_CIDRS}')
        if prefix_list is not None:
            prefix_list = str(prefix_list).strip()
            if not self._PREFIX_LIST_ID.match(prefix_list):
                raise ValueError(f'{Settings.ECS_STAGING_CANARY_SOURCE_PREFIX_LIST} is not a managed prefix'
                                 f' list id (pl- followed by 8 or 17 hex digits): {prefix_list!r}')
            return 'prefix_list', prefix_list
        return 'cidrs', parse_source_cidrs(cidrs, key=Settings.ECS_STAGING_CANARY_SOURCE_CIDRS)

    def colour_closed(self, colour: str) -> bool:
        """ The staging canary opens STAGING_CANARY_COLOUR only; otherwise both colours follow
            bootstrap_closed(). """
        if self.staging_canary():
            return colour != self.STAGING_CANARY_COLOUR
        return super().colour_closed(colour)

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ In the closed bootstrap stage the (permanent) ALB security group keeps its logical id,
            description and VPC but has no ingress rule; leaving the stage restores the normal
            80/443 ingress as an in-place update. The staging canary admits 443/80 from its one
            validated source only (the closed colour has no listener, so it still accepts nothing). """
        if self.staging_canary():
            kind, source = self.staging_canary_source()
            if kind == 'prefix_list':
                rules = [SecurityGroupRule(IpProtocol='tcp', FromPort=port, ToPort=port, SourcePrefixListId=source)
                         for port in self.STAGING_CANARY_PORTS]
            else:
                rules = [SecurityGroupRule(IpProtocol='tcp', FromPort=port, ToPort=port,
                                           **({'CidrIp': cidr} if ipaddress.ip_network(cidr).version == 4
                                              else {'CidrIpv6': cidr}))
                         for port in self.STAGING_CANARY_PORTS for cidr in source]
            return SecurityGroup(
                self.name.logical_id('LBSecurityGroup'),
                GroupDescription="Web load balancer security group.",
                VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
                SecurityGroupIngress=rules,
                Tags=self.tags.cost_tag_array()
            )
        if not self.bootstrap_closed():
            return super().ecs_lb_security_group()
        return SecurityGroup(
            self.name.logical_id('LBSecurityGroup'),
            GroupDescription="Web load balancer security group.",
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array()
        )

    def _canary_count(self, service, count):
        """ Pin a canary service's DesiredCount to its explicit count (and the inherited capacity
            provider Base, via concurrency, to the same number). """
        service.DesiredCount = count
        return service

    def ecs_portal_service(self, *args, **kwargs):
        if not self.staging_canary():
            return super().ecs_portal_service(*args, **kwargs)
        kwargs['concurrency'] = self.STAGING_CANARY_PORTAL_COUNT
        return self._canary_count(super().ecs_portal_service(*args, **kwargs), self.STAGING_CANARY_PORTAL_COUNT)

    def ecs_indexer_service(self, *args, **kwargs):
        if not self.staging_canary():
            return super().ecs_indexer_service(*args, **kwargs)
        kwargs['concurrency'] = self.STAGING_CANARY_INDEXER_COUNT
        return self._canary_count(super().ecs_indexer_service(*args, **kwargs), self.STAGING_CANARY_INDEXER_COUNT)

    def ecs_ingester_service(self, *args, **kwargs):
        if not self.staging_canary():
            return super().ecs_ingester_service(*args, **kwargs)
        kwargs['concurrency'] = self.STAGING_CANARY_INGESTER_COUNT
        return self._canary_count(super().ecs_ingester_service(*args, **kwargs), self.STAGING_CANARY_INGESTER_COUNT)

    def ecs_indexer_task(self, cpu='256', memory='512', **kwargs):
        """ ECSBlueGreen pins the indexer at 256/512 and ignores ecs.indexer.cpu/memory. Once the indexer
            carries the observability sidecars (FireLens alone reserves 256 MiB) honour those settings, as
            the standalone stack and the blue/green ingester already do; their defaults are the same
            256/512, and with the sidecars off the render is unchanged. """
        if self.observes(ApplicationTypes.INDEXER):
            cpu = memory = None
        return super().ecs_indexer_task(cpu=cpu, memory=memory, **kwargs)
