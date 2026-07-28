"""
Tests for the CrowdStrike Falcon container-sensor sidecar support on ECS task definitions.

The demonstrated (vendor) contract, applied to every ECS task variant when crowdstrike.enabled:
  * a non-essential 'falcon-container' sidecar pulls the falcon-sensor image and prepares a shared
    task-level 'crowdstrike-falcon-volume' (Host volume), with the Falcon CID injected from Secrets
    Manager as FALCONCTL_OPT_FALCONCTL_CID and FALCONCTL_OPT_BACKEND set;
  * the application container mounts that volume READ-ONLY, is wrapped by the CrowdStrike loader
    EntryPoint, and dependsOn the sidecar with condition SUCCESS;
  * task-level Volumes declares the shared volume once.

The default (crowdstrike.enabled false) must leave every task definition byte-identical to before:
single container, no Volumes, no EntryPoint/DependsOn/MountPoints/Secrets. That preservation is the
regression guard for the ~11 existing task definitions across the CGAP/Fourfront/blue-green/SRCE
variants.
"""
import pytest
from unittest import mock

from src.parts import ecs as ecs_mod
from src.parts.ecs import C4ECSApplication
from src.parts.fourfront_ecs import FourfrontECSApplication
from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.srce_ecs import C4SRCEECSApplication
from src.parts.logging import C4LoggingExports
from src.constants import Settings
from src.c4name import C4Name
from src.part import C4Tags, C4Account


DEFAULT_ENTRYPOINT = ['/tmp/CrowdStrike/rootfs/lib/init']


def _config(enabled, entrypoint=DEFAULT_ENTRYPOINT, extra=None):
    cfg = {
        Settings.APP_KIND: 'smaht',
        Settings.ENV_NAME: 'smaht-test',
        Settings.IDENTITY: 'C4AppConfigSmahtTest',
        Settings.ECS_IMAGE_TAG: 'latest',
        Settings.CROWDSTRIKE_ENABLED: enabled,
    }
    if entrypoint is not None:
        cfg[Settings.CROWDSTRIKE_ENTRYPOINT] = entrypoint
    if extra:
        cfg.update(extra)

    def _get(var, default=None, use_default_if_empty=True):
        return cfg.get(var, default)

    return _get


def _make_part(cls):
    return cls(name=C4Name('c4-ecs-main', title_token='C4ECSMain'), tags=C4Tags(),
               account=C4Account(account_number='123456789', creds_file='/dev/null'))


def _containers(task):
    return task.to_dict()['Properties']['ContainerDefinitions']


def _by_name(containers, name):
    return next(c for c in containers if c['Name'] == name)


# The full set of (class, task-builder callable factory, app-container-name) we assert on. SRCE
# inherits C4ECSApplication's task builders verbatim, so exercising it proves the mixin path too.
def _task_matrix():
    return [
        ('cgap-portal', C4ECSApplication, lambda p: p.ecs_portal_task(), 'portal'),
        ('cgap-indexer', C4ECSApplication, lambda p: p.ecs_indexer_task(), 'Indexer'),
        ('cgap-ingester', C4ECSApplication, lambda p: p.ecs_ingester_task(), 'Ingester'),
        ('cgap-deploy', C4ECSApplication, lambda p: p.ecs_deployment_task(), 'DeploymentAction'),
        ('cgap-initial-deploy', C4ECSApplication, lambda p: p.ecs_deployment_task(initial=True), 'DeploymentAction'),
        ('srce-portal', C4SRCEECSApplication, lambda p: p.ecs_portal_task(), 'portal'),
        ('srce-deploy', C4SRCEECSApplication, lambda p: p.ecs_deployment_task(), 'DeploymentAction'),
        ('ff-portal', FourfrontECSApplication, lambda p: p.ecs_portal_task(), 'portal'),
        ('ff-indexer', FourfrontECSApplication, lambda p: p.ecs_indexer_task(), 'Indexer'),
        ('ff-deploy', FourfrontECSApplication, lambda p: p.ecs_deployment_task(), 'DeploymentAction'),
    ]


@pytest.mark.parametrize('label,cls,builder,app_name', _task_matrix(),
                         ids=[m[0] for m in _task_matrix()])
def test_disabled_preserves_original_single_container(label, cls, builder, app_name):
    """ With crowdstrike.enabled false, every task definition is unchanged: one container, no shared
        volume, and no CrowdStrike wiring on the application container. """
    part = _make_part(cls)
    with mock.patch.object(ecs_mod.ConfigManager, 'get_config_setting', side_effect=_config(False)):
        props = builder(part).to_dict()['Properties']
    containers = props['ContainerDefinitions']
    assert len(containers) == 1
    assert containers[0]['Name'] == app_name
    assert containers[0]['Essential'] is True
    assert 'Volumes' not in props
    for absent in ('EntryPoint', 'DependsOn', 'MountPoints', 'Secrets'):
        assert absent not in containers[0], f'{absent} leaked into non-CrowdStrike {label} task'
    # The falcon sidecar must not appear.
    assert all(c['Name'] != C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME for c in containers)


@pytest.mark.parametrize('label,cls,builder,app_name', _task_matrix(),
                         ids=[m[0] for m in _task_matrix()])
def test_enabled_wraps_every_task_with_falcon_sidecar(label, cls, builder, app_name):
    """ With crowdstrike.enabled, every task definition gains the sidecar + shared volume and the app
        container is wrapped per the demonstrated contract. """
    part = _make_part(cls)
    with mock.patch.object(ecs_mod.ConfigManager, 'get_config_setting', side_effect=_config(True)):
        props = builder(part).to_dict()['Properties']
    containers = props['ContainerDefinitions']

    # Exactly the app container + the falcon sidecar, in that order.
    assert [c['Name'] for c in containers] == [app_name, C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME]
    app = _by_name(containers, app_name)
    sidecar = _by_name(containers, C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME)

    # essential flags: app stays essential, sidecar is non-essential (prepare-and-exit init).
    assert app['Essential'] is True
    assert sidecar['Essential'] is False

    # task-level shared volume, declared once, host-backed (ephemeral).
    assert props['Volumes'] == [{'Name': C4ECSApplication.CROWDSTRIKE_VOLUME_NAME, 'Host': {}}]

    # app mounts the shared volume READ-ONLY; sidecar mounts it read-write to populate it.
    app_mount = app['MountPoints'][0]
    assert app_mount['SourceVolume'] == C4ECSApplication.CROWDSTRIKE_VOLUME_NAME
    assert app_mount['ContainerPath'] == '/tmp/CrowdStrike'
    assert app_mount['ReadOnly'] is True
    sidecar_mount = sidecar['MountPoints'][0]
    assert sidecar_mount['SourceVolume'] == C4ECSApplication.CROWDSTRIKE_VOLUME_NAME
    assert sidecar_mount['ReadOnly'] is False

    # entrypoint ordering: the CrowdStrike loader prefix is first (observable form of the wrap).
    assert app['EntryPoint'] == DEFAULT_ENTRYPOINT
    assert app['EntryPoint'][0] == DEFAULT_ENTRYPOINT[0]

    # dependency: app waits for the sidecar to complete SUCCESSfully.
    assert app['DependsOn'] == [{'ContainerName': C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME,
                                 'Condition': 'SUCCESS'}]

    # CID secret injected on the sidecar via the appconfig-owned export (never a literal ARN).
    cid = sidecar['Secrets'][0]
    assert cid['Name'] == 'FALCONCTL_OPT_FALCONCTL_CID'
    value_from = cid['ValueFrom']
    assert 'Fn::ImportValue' in value_from
    assert 'ExportFalconCID' in value_from['Fn::ImportValue']['Fn::Sub']
    # backend env var present.
    assert {'Name': 'FALCONCTL_OPT_BACKEND', 'Value': 'bpf'} in sidecar['Environment']

    # sidecar image comes from the falcon-sensor ECR repo export.
    sidecar_image = sidecar['Image']['Fn::Join'][1][0]
    assert 'FalconSensorURL' in sidecar_image['Fn::ImportValue']['Fn::Sub']

    # sidecar has its own awslogs config (valid logging), distinct stream prefix ending -falcon.
    log_opts = sidecar['LogConfiguration']['Options']
    assert log_opts['awslogs-stream-prefix'].endswith('-falcon')

    # no literal AWS account id / secret ARN anywhere in the emitted task.
    import json as _json
    blob = _json.dumps(props, default=str)
    assert '527768939855' not in blob
    assert 'arn:aws:secretsmanager' not in blob


def test_enabled_but_no_entrypoint_raises():
    """ crowdstrike.enabled with no crowdstrike.entrypoint must fail loudly at build time rather than
        emit a task definition that validates but never runs the application. """
    part = _make_part(C4ECSApplication)
    with mock.patch.object(ecs_mod.ConfigManager, 'get_config_setting',
                           side_effect=_config(True, entrypoint=None)):
        with pytest.raises(RuntimeError, match='crowdstrike.entrypoint'):
            part.ecs_deployment_task()


def test_entrypoint_accepts_comma_separated_string():
    """ The loader entrypoint may be supplied as a comma-separated string (config values round-trip
        through os.environ as strings). """
    part = _make_part(C4ECSApplication)
    with mock.patch.object(ecs_mod.ConfigManager, 'get_config_setting',
                           side_effect=_config(True, entrypoint='/a/loader, --flag, /entrypoint.sh')):
        app = _by_name(_containers(part.ecs_deployment_task()), 'DeploymentAction')
    assert app['EntryPoint'] == ['/a/loader', '--flag', '/entrypoint.sh']


def test_blue_green_sidecar_uses_per_color_log_group_and_prefix():
    """ Blue/green tasks must route their falcon sidecar to the SAME per-color log group as the app
        container, with a color-distinct stream prefix, so blue and green streams do not collide. """
    part = _make_part(ECSBlueGreen)
    with mock.patch.object(ecs_mod.ConfigManager, 'get_config_setting', side_effect=_config(True)):
        blue = part.ecs_portal_task(image_tag='blue', log_group_export=C4LoggingExports.APPLICATION_LOG_GROUP_BLUE,
                                    identity='C4AppConfigBlue')
        green = part.ecs_portal_task(image_tag='green', log_group_export=C4LoggingExports.APPLICATION_LOG_GROUP_GREEN,
                                     identity='C4AppConfigGreen')
    blue_sidecar = _by_name(_containers(blue), C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME)
    green_sidecar = _by_name(_containers(green), C4ECSApplication.FALCON_SIDECAR_CONTAINER_NAME)

    # per-color log group threaded through to the sidecar (not the default application log group).
    assert (C4LoggingExports.APPLICATION_LOG_GROUP_BLUE in
            blue_sidecar['LogConfiguration']['Options']['awslogs-group']['Fn::ImportValue']['Fn::Sub'])
    assert (C4LoggingExports.APPLICATION_LOG_GROUP_GREEN in
            green_sidecar['LogConfiguration']['Options']['awslogs-group']['Fn::ImportValue']['Fn::Sub'])

    # stream prefixes are color-distinct.
    blue_prefix = blue_sidecar['LogConfiguration']['Options']['awslogs-stream-prefix']
    green_prefix = green_sidecar['LogConfiguration']['Options']['awslogs-stream-prefix']
    assert blue_prefix != green_prefix
    assert 'blue' in blue_prefix and 'green' in green_prefix
