import re

from troposphere import Join
from troposphere.ecs import (
    ContainerDefinition,
    ContainerDependency,
    Environment,
    FirelensConfiguration,
    LogConfiguration,
    MountPoint,
    Secret,
)

from ..base import ConfigManager
from ..constants import Settings
from .ecr import C4ECRExports
from .srce_backend_tls import SRCEBackendTLSMixin


class SRCEObservabilityMixin:
    """
    Observability sidecars for the SRCE ECS stacks (standalone and blue/green): the CrowdStrike Falcon
    sensor and a FireLens (Fluent Bit) log router shipping to Splunk HEC. The shapes match what the SMaHT
    dev SRCE deployment runs (hand-registered there), so a production deployment can carry them in IaC.

    Off unless crowdstrike.cid_secret_arn is set or splunk.enabled is true, in which case it replaces the
    shared _crowdstrike_task_kwargs hook of C4ECSApplication; otherwise that hook (including the legacy
    crowdstrike.enabled wiring) runs unchanged, so no existing render moves.

    * Falcon (crowdstrike.cid_secret_arn): the CID comes from that existing secret, never from the AppConfig
      export, so the template declares no AppConfig parameter and nothing here needs crowdstrike.enabled
      (which only ever adds credential stubs to the AppConfig template). The sensor image is this
      account's falcon-sensor ECR repository pinned by digest (crowdstrike.sensor_image_digest). The
      sidecar runs as 0:0 and copies its runtime into the shared volume; the application container
      mounts it read-only, is wrapped by crowdstrike.entrypoint, receives FALCONCTL_OPT_CID and waits for
      the sidecar's SUCCESS.
    * Splunk (splunk.enabled): an essential splunk-firelens sidecar (fluentbit, ECS log metadata, the
      image's default parser) and an awsfirelens log driver on the application container sending to
      splunk.hec_host:443 with TLS verification on, the token injected from splunk.hec_token_secret_arn and
      sourcetype ecs:<app kind>:<role>_v1. The application container waits for the router's START.

    Sidecars apply to the roles in ecs.observability_roles (default portal, indexer, ingester and
    deployment); other tasks, including initial-deployment by default, are left exactly as they are.
    Every container change appends to what is already there, so backend TLS secrets and ports survive.
    Sidecar logs go to the stack's existing application log group (per colour in blue/green), so no log
    group, secret, parameter or other resource is added.
    """
    FIRELENS_CONTAINER_NAME = 'splunk-firelens'
    FIRELENS_CPU = 128
    FIRELENS_MEMORY_RESERVATION = 256
    FIRELENS_USER = '0'
    FIRELENS_DEPENDS_CONDITION = 'START'
    SPLUNK_TOKEN_SECRET_OPTION = 'splunk_token'
    SPLUNK_HEC_PORT = '443'
    FALCON_SIDECAR_USER = '0:0'
    # The application container's copy of the CID (the sidecar's is FALCONCTL_OPT_FALCONCTL_CID).
    FALCON_APP_CID_SECRET_ENV_NAME = 'FALCONCTL_OPT_CID'

    OBSERVABILITY_ROLES = ('portal', 'indexer', 'ingester', 'deployment', 'initial-deployment')
    DEFAULT_OBSERVABILITY_ROLES = ('portal', 'indexer', 'ingester', 'deployment')

    _DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
    _PINNED_IMAGE = re.compile(r'^[A-Za-z0-9.-]+(?::\d+)?/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$')
    _HOSTNAME = re.compile(r'^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                           r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$')
    _SPLUNK_INDEX = re.compile(r'^[a-z0-9_][a-z0-9_-]{0,79}$')

    # --- settings ---------------------------------------------------------------------------------

    @staticmethod
    def _secret_arn_setting(key):
        """ A complete Secrets Manager secret ARN from config, or None when unset. """
        value = ConfigManager.get_config_setting(key, default=None)
        if value is None:
            return None
        if not isinstance(value, str) or not SRCEBackendTLSMixin._SECRET_ARN.match(value.strip()):
            raise ValueError(f'{key} must be the complete Secrets Manager secret ARN, ending in the secret'
                             f' name and its 6-character suffix, not {value!r}')
        return value.strip()

    @staticmethod
    def _required_setting(key, pattern, what):
        value = ConfigManager.get_config_setting(key, default=None)
        if not isinstance(value, str) or not pattern.match(value.strip()):
            raise ValueError(f'{key} must be {what}, not {value!r}')
        return value.strip()

    def falcon_cid_secret_arn(self):
        return self._secret_arn_setting(Settings.CROWDSTRIKE_CID_SECRET_ARN)

    def splunk_enabled(self) -> bool:
        """ splunk.enabled parsed strictly: unset or false -> off; true -> on; anything else raises. """
        value = ConfigManager.get_config_setting(Settings.SPLUNK_ENABLED, default=None)
        if value is None or isinstance(value, bool):
            return bool(value)
        raise ValueError(f'{Settings.SPLUNK_ENABLED} must be true or false, not {value!r}')

    def observability_enabled(self) -> bool:
        return bool(self.falcon_cid_secret_arn()) or self.splunk_enabled()

    def observability_roles(self) -> tuple:
        value = ConfigManager.get_config_setting(Settings.ECS_OBSERVABILITY_ROLES, default=None)
        if value is None:
            return self.DEFAULT_OBSERVABILITY_ROLES
        roles = self._parse_crowdstrike_entrypoint(value)  # the shared list-setting parser
        unknown = [role for role in roles if role not in self.OBSERVABILITY_ROLES]
        if not roles or unknown:
            raise ValueError(f'{Settings.ECS_OBSERVABILITY_ROLES} must be a non-empty list drawn from'
                             f' {list(self.OBSERVABILITY_ROLES)}, not {value!r}')
        return tuple(roles)

    def observes(self, role) -> bool:
        """ Whether the parity sidecars are added to the task of this role. """
        return self.observability_enabled() and role in self.observability_roles()

    def falcon_sensor_image_digest(self):
        return self._required_setting(Settings.CROWDSTRIKE_SENSOR_IMAGE_DIGEST, self._DIGEST,
                                      'the falcon-sensor image digest, sha256: and 64 hex digits')

    def splunk_hec_host(self):
        return self._required_setting(Settings.SPLUNK_HEC_HOST, self._HOSTNAME,
                                      'the Splunk HEC hostname (no scheme, port or path)')

    def splunk_hec_token_secret_arn(self):
        arn = self._secret_arn_setting(Settings.SPLUNK_HEC_TOKEN_SECRET_ARN)
        if not arn:
            raise ValueError(f'{Settings.SPLUNK_ENABLED} is true but {Settings.SPLUNK_HEC_TOKEN_SECRET_ARN}'
                             f' is not set')
        return arn

    def splunk_firelens_image(self):
        return self._required_setting(Settings.SPLUNK_FIRELENS_IMAGE, self._PINNED_IMAGE,
                                      'the aws-for-fluent-bit image pinned by digest (<registry>/<repo>@sha256:...)')

    def splunk_event_index(self):
        value = ConfigManager.get_config_setting(Settings.SPLUNK_EVENT_INDEX, default=None)
        if value is None:
            return None
        return self._required_setting(Settings.SPLUNK_EVENT_INDEX, self._SPLUNK_INDEX, 'a Splunk index name')

    # --- template hooks ---------------------------------------------------------------------------

    def crowdstrike_template_parameters(self) -> list:
        """ The explicit CID secret replaces the AppConfig import, and with it the AppConfig parameter. """
        if self.falcon_cid_secret_arn():
            return []
        return super().crowdstrike_template_parameters()

    def _crowdstrike_task_kwargs(self, app_container: ContainerDefinition,
                                 sidecar_stream_prefix, log_group_export=None, role=None) -> dict:
        if not self.observability_enabled():
            return super()._crowdstrike_task_kwargs(app_container, sidecar_stream_prefix,
                                                    log_group_export=log_group_export, role=role)
        falcon = bool(self.falcon_cid_secret_arn())
        if not falcon and self.crowdstrike_enabled():
            raise ValueError(
                f'{Settings.SPLUNK_ENABLED} cannot be combined with the AppConfig-sourced Falcon wiring'
                f' ({Settings.CROWDSTRIKE_ENABLED} without {Settings.CROWDSTRIKE_CID_SECRET_ARN}). Set'
                f' {Settings.CROWDSTRIKE_CID_SECRET_ARN}, or turn Falcon off.')
        if role not in self.OBSERVABILITY_ROLES:
            raise ValueError(f'Unknown ECS task role {role!r}')
        if role not in self.observability_roles():
            return {'ContainerDefinitions': [app_container]}
        if not sidecar_stream_prefix.endswith('-falcon'):
            raise ValueError(f'Unexpected sidecar stream prefix {sidecar_stream_prefix!r}')
        stream_base = sidecar_stream_prefix[:-len('-falcon')]

        kwargs = {'ContainerDefinitions': [app_container]}
        if falcon:
            kwargs['ContainerDefinitions'].append(
                self._with_falcon(app_container, f'{stream_base}-falcon', log_group_export))
            kwargs['Volumes'] = [self._crowdstrike_volume()]
        if self.splunk_enabled():
            kwargs['ContainerDefinitions'].append(
                self._with_firelens(app_container, role, f'{stream_base}-firelens', log_group_export))
        return kwargs

    @staticmethod
    def _extend(container, prop, items):
        setattr(container, prop, list(getattr(container, prop, None) or []) + items)

    def _with_falcon(self, app_container, stream_prefix, log_group_export) -> ContainerDefinition:
        """ Wrap the application container for Falcon and return the sensor sidecar. """
        cid_arn = self.falcon_cid_secret_arn()
        mount_path = self.crowdstrike_mount_path()
        self._extend(app_container, 'MountPoints', [MountPoint(
            SourceVolume=self.CROWDSTRIKE_VOLUME_NAME, ContainerPath=mount_path, ReadOnly=True)])
        app_container.EntryPoint = self.crowdstrike_entrypoint()
        self._extend(app_container, 'Secrets', [Secret(Name=self.FALCON_APP_CID_SECRET_ENV_NAME, ValueFrom=cid_arn)])
        self._extend(app_container, 'DependsOn', [ContainerDependency(
            ContainerName=self.FALCON_SIDECAR_CONTAINER_NAME, Condition=self.FALCON_SIDECAR_DEPENDS_CONDITION)])

        # Copy the sensor runtime into the shared volume, then exit 0 (the SUCCESS the app waits for).
        copy_runtime = (f'chmod u+rwx {mount_path} && mkdir {mount_path}/rootfs'
                        f' && cp -r /bin /etc /lib64 /usr /entrypoint-ecs.sh {mount_path}/rootfs'
                        f' && chmod -R a=rX {mount_path}')
        sidecar = dict(
            Name=self.FALCON_SIDECAR_CONTAINER_NAME,
            Essential=False,
            Image=Join('', [self.ECR_EXPORTS.import_value(C4ECRExports.FALCON_SENSOR_URL),
                            '@', self.falcon_sensor_image_digest()]),
            User=self.FALCON_SIDECAR_USER,
            EntryPoint=['/bin/bash', '-c', copy_runtime],
            Secrets=[Secret(Name=self.FALCON_CID_SECRET_ENV_NAME, ValueFrom=cid_arn)],
            MountPoints=[MountPoint(SourceVolume=self.CROWDSTRIKE_VOLUME_NAME, ContainerPath=mount_path,
                                    ReadOnly=False)],
            LogConfiguration=self._awslogs_config(stream_prefix, log_group_export),
        )
        # Dev's sidecar sets no backend; pass one through only when crowdstrike.backend is set explicitly.
        backend = ConfigManager.get_config_setting(Settings.CROWDSTRIKE_BACKEND, default=None)
        if backend:
            sidecar['Environment'] = [Environment(Name=self.FALCON_BACKEND_ENV_NAME, Value=backend)]
        return ContainerDefinition(**sidecar)

    def _with_firelens(self, app_container, role, stream_prefix, log_group_export) -> ContainerDefinition:
        """ Route the application container's logs to Splunk HEC and return the FireLens sidecar. """
        app_kind = ConfigManager.get_config_setting(Settings.APP_KIND)
        options = {
            'Name': 'splunk',
            'Host': self.splunk_hec_host(),
            'Port': self.SPLUNK_HEC_PORT,
            'tls': 'on',
            'tls.verify': 'on',
            'compress': 'gzip',
            'event_sourcetype': f'ecs:{app_kind}:{role.replace("-", "_")}_v1',
        }
        index = self.splunk_event_index()
        if index:
            options['event_index'] = index
        app_container.LogConfiguration = LogConfiguration(
            LogDriver='awsfirelens',
            Options=options,
            SecretOptions=[Secret(Name=self.SPLUNK_TOKEN_SECRET_OPTION, ValueFrom=self.splunk_hec_token_secret_arn())],
        )
        self._extend(app_container, 'DependsOn', [ContainerDependency(
            ContainerName=self.FIRELENS_CONTAINER_NAME, Condition=self.FIRELENS_DEPENDS_CONDITION)])
        return ContainerDefinition(
            Name=self.FIRELENS_CONTAINER_NAME,
            Essential=True,
            Image=self.splunk_firelens_image(),
            User=self.FIRELENS_USER,
            Cpu=self.FIRELENS_CPU,
            MemoryReservation=self.FIRELENS_MEMORY_RESERVATION,
            FirelensConfiguration=FirelensConfiguration(
                Type='fluentbit', Options={'enable-ecs-log-metadata': 'true'}),
            LogConfiguration=self._awslogs_config(stream_prefix, log_group_export),
        )
