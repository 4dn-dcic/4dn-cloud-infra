""" Falcon and Splunk (FireLens) parity sidecars for the SRCE ECS stacks (SRCEObservabilityMixin).

Asserts on full synthesized templates: the container shapes the SMaHT dev SRCE deployment runs (portal,
indexer, ingester and deployment; initial-deployment untouched), composition with backend TLS, the
closed bootstrap stage, that the explicit CID secret removes the AppConfig dependency, that IAM and
AppConfig render identically, the indexer sizing gate and strict input validation. Cross-revision parity
of the off renders is proven separately against the pre-change tree (see the PR).
"""
import copy

import pytest

from src.parts.appconfig import C4AppConfig
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.iam import C4IAM
from src.parts.srce_ecs import C4SRCEECSApplication
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen

SRCE = {'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1', 'vpc.cidr': '10.10.0.0/16'}
CERT = 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000'
TLS_SECRET = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/portal/nginx-tls-AbC123'
CID_SECRET = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/falcon-cid-DeF456'
HEC_SECRET = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/splunk-hec-token-GhI789'
DIGEST = 'sha256:' + 'a' * 64
FIRELENS_IMAGE = 'public.ecr.aws/aws-observability/aws-for-fluent-bit@sha256:' + 'b' * 64
LOADER = ['/tmp/CrowdStrike/rootfs/lib64/ld-linux-x86-64.so.2', '--library-path', '/tmp/CrowdStrike/rootfs/lib64',
          '/tmp/CrowdStrike/rootfs/bin/bash', '/tmp/CrowdStrike/rootfs/entrypoint-ecs.sh',
          '/home/nginx/smaht-portal/entrypoint.sh']
FALCON = {'crowdstrike.cid_secret_arn': CID_SECRET, 'crowdstrike.sensor_image_digest': DIGEST,
          'crowdstrike.entrypoint': str(LOADER).replace("'", '"')}
SPLUNK = {'splunk.enabled': True, 'splunk.hec_host': 'http-inputs.example.splunkcloud.com',
          'splunk.hec_token_secret_arn': HEC_SECRET, 'splunk.firelens_image': FIRELENS_IMAGE}
PARITY = {**FALCON, **SPLUNK}
CLOSED = {'ecs.bootstrap_closed': True, 'ecs.backend_tls_secret_arn': TLS_SECRET}
NORMAL_TLS = {'ecs.lb_certificate_arn': CERT, 'ecs.backend_tls_secret_arn': TLS_SECRET}

VARIANTS = {'standalone': (C4SRCEECSApplication, 'standalone'), 'blue/green': (SRCEECSBlueGreen, 'blue/green')}
# Task logical id after '<app kind><colour>' -> (role, application container name).
TASK_ROLES = {'Portal': ('portal', 'Portal'), 'portal': ('portal', 'portal'), 'Indexer': ('indexer', 'Indexer'),
              'Ingester': ('ingester', 'Ingester'), 'Deployment': ('deployment', 'DeploymentAction'),
              'InitialDeployment': ('initial-deployment', 'DeploymentAction')}

# What dev runs, as recorded from its task definitions (images, ARNs and log destinations aside).
COPY_RUNTIME = ('chmod u+rwx /tmp/CrowdStrike && mkdir /tmp/CrowdStrike/rootfs && cp -r /bin /etc /lib64 /usr'
                ' /entrypoint-ecs.sh /tmp/CrowdStrike/rootfs && chmod -R a=rX /tmp/CrowdStrike')
FALCON_SIDECAR = {
    'Name': 'falcon-container', 'Essential': False, 'User': '0:0', 'EntryPoint': ['/bin/bash', '-c', COPY_RUNTIME],
    'Secrets': [{'Name': 'FALCONCTL_OPT_FALCONCTL_CID', 'ValueFrom': CID_SECRET}],
    'MountPoints': [{'SourceVolume': 'crowdstrike-falcon-volume', 'ContainerPath': '/tmp/CrowdStrike',
                     'ReadOnly': False}],
}
FIRELENS_SIDECAR = {
    'Name': 'splunk-firelens', 'Essential': True, 'User': '0', 'Cpu': 128, 'MemoryReservation': 256,
    'Image': FIRELENS_IMAGE,
    'FirelensConfiguration': {'Type': 'fluentbit', 'Options': {'enable-ecs-log-metadata': 'true'}},
}


@pytest.fixture(autouse=True)
def offline_appconfig(monkeypatch):
    """ The AppConfig build resolves the OpenSearch URL by describing stacks; pin it offline. """
    monkeypatch.setattr(ApplicationConfigurationSecrets, 'get_es_url',
                        classmethod(lambda cls: 'https://es.invalid:443'))


def render(synthesis_config, synthesize, variant='blue/green', extra=None, cls=None):
    variant_cls, deployment = VARIANTS[variant]
    synthesis_config('smaht', deployment, {**SRCE, **(extra or {})})
    return synthesize(cls or variant_cls)


def tasks(template, variant):
    """ (logical id, role, app container name, TaskDefinition) for every task in the template. """
    colours = ('blue', 'green') if variant == 'blue/green' else ('',)
    found = []
    for key, res in template['Resources'].items():
        if res['Type'] != 'AWS::ECS::TaskDefinition':
            continue
        assert key[:len('smaht')].lower() == 'smaht', key
        colour = next(c for c in colours if key[len('smaht'):].startswith(c))
        found.append((key, *TASK_ROLES[key[len('smaht') + len(colour):]], res))
    assert len(found) == (10 if variant == 'blue/green' else 5)
    return found


def by_name(task, name):
    return next(c for c in task['Properties']['ContainerDefinitions'] if c['Name'] == name)


def without_task_definitions(template):
    stripped = copy.deepcopy(template)
    stripped['Resources'] = {k: r for k, r in stripped['Resources'].items()
                             if r['Type'] != 'AWS::ECS::TaskDefinition'}
    return stripped


@pytest.mark.parametrize('stage', [CLOSED, NORMAL_TLS], ids=['closed', 'normal-tls'])
@pytest.mark.parametrize('variant', sorted(VARIANTS))
def test_parity_matches_dev_and_touches_only_task_definitions(synthesis_config, synthesize, variant, stage):
    if variant == 'standalone' and stage is CLOSED:
        pytest.skip('the closed bootstrap stage is blue/green only')
    off = render(synthesis_config, synthesize, variant, stage)
    on = render(synthesis_config, synthesize, variant, {**stage, **PARITY})

    # Same parameters, outputs and non-task resources: nothing is added, and no AppConfig import.
    assert without_task_definitions(on) == without_task_definitions(off)
    assert set(on['Resources']) == set(off['Resources'])
    assert 'AppConfigStackNameParameter' not in on['Parameters']
    assert 'AppConfigStackNameParameter' not in str(on)  # no Fn::ImportValue of an AppConfig export

    off_tasks = {key: res for key, _, _, res in tasks(off, variant)}
    for key, role, app_name, task in tasks(on, variant):
        if role == 'initial-deployment':
            assert task == off_tasks[key], 'initial-deployment must be untouched by default'
            continue
        props = task['Properties']
        assert [c['Name'] for c in props['ContainerDefinitions']] == [app_name, 'falcon-container', 'splunk-firelens']
        assert props['Volumes'] == [{'Name': 'crowdstrike-falcon-volume', 'Host': {}}]

        falcon = by_name(task, 'falcon-container')
        assert {k: falcon[k] for k in FALCON_SIDECAR} == FALCON_SIDECAR
        assert 'Environment' not in falcon  # dev's sidecar sets no backend
        sensor_repo = {'Fn::ImportValue': {'Fn::Sub': '${ECRStackNameParameter}-FalconSensorURL'}}
        assert falcon['Image'] == {'Fn::Join': ['', [sensor_repo, '@', DIGEST]]}
        firelens = by_name(task, 'splunk-firelens')
        assert {k: firelens[k] for k in FIRELENS_SIDECAR} == FIRELENS_SIDECAR
        off_app = by_name(off_tasks[key], app_name)
        for sidecar, suffix in [(falcon, 'falcon'), (firelens, 'firelens')]:
            log = sidecar['LogConfiguration']
            assert log['LogDriver'] == 'awslogs'
            # the stack's own (per-colour) log group, which the logging stack creates with retention
            assert log['Options']['awslogs-group'] == off_app['LogConfiguration']['Options']['awslogs-group']
            assert log['Options']['awslogs-stream-prefix'].endswith(f'-{suffix}')

        app = by_name(task, app_name)
        assert app['EntryPoint'] == LOADER
        assert app['MountPoints'] == [{'SourceVolume': 'crowdstrike-falcon-volume', 'ContainerPath': '/tmp/CrowdStrike',
                                       'ReadOnly': True}]
        assert app['DependsOn'] == [{'ContainerName': 'falcon-container', 'Condition': 'SUCCESS'},
                                    {'ContainerName': 'splunk-firelens', 'Condition': 'START'}]
        assert app['Secrets'][-1] == {'Name': 'FALCONCTL_OPT_CID', 'ValueFrom': CID_SECRET}
        assert app['LogConfiguration'] == {
            'LogDriver': 'awsfirelens',
            'Options': {'Name': 'splunk', 'Host': 'http-inputs.example.splunkcloud.com', 'Port': '443', 'tls': 'on',
                        'tls.verify': 'on', 'compress': 'gzip', 'event_sourcetype': f'ecs:smaht:{role}_v1'},
            'SecretOptions': [{'Name': 'splunk_token', 'ValueFrom': HEC_SECRET}],
        }
        # Apart from these, the application container is exactly as before (environment, image, ports).
        changed = {'EntryPoint', 'MountPoints', 'DependsOn', 'Secrets', 'LogConfiguration'}
        assert {k: v for k, v in app.items() if k not in changed} == \
            {k: v for k, v in off_app.items() if k not in changed}
        assert app['Secrets'][:-1] == off_app.get('Secrets', [])
        # Task sizing and roles are unchanged (the indexer only moves when ecs.indexer.* is set).
        assert {k: v for k, v in props.items() if k not in ('ContainerDefinitions', 'Volumes')} == \
            {k: v for k, v in off_tasks[key]['Properties'].items() if k != 'ContainerDefinitions'}


@pytest.mark.parametrize('variant', sorted(VARIANTS))
def test_backend_tls_survives_on_the_portal(synthesis_config, synthesize, variant):
    template = render(synthesis_config, synthesize, variant, {**NORMAL_TLS, **PARITY})
    for key, role, app_name, task in tasks(template, variant):
        if role != 'portal':
            continue
        portal = by_name(task, app_name)
        assert [s['Name'] for s in portal['Secrets']] == ['NGINX_SSL_CERTIFICATE', 'NGINX_SSL_CERTIFICATE_KEY',
                                                          'FALCONCTL_OPT_CID']
        assert portal['PortMappings'] == [{'ContainerPort': 8443}]
        assert {'Name': 'NGINX_TLS_ENABLED', 'Value': 'true'} in portal['Environment']
        assert len(portal['DependsOn']) == 2
        # the sidecars carry no TLS material and no port
        for sidecar in ('falcon-container', 'splunk-firelens'):
            assert 'NGINX' not in str(by_name(task, sidecar)) and 'PortMappings' not in by_name(task, sidecar)


def test_closed_bootstrap_stays_closed(synthesis_config, synthesize):
    template = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **PARITY})
    types = [r['Type'] for r in template['Resources'].values()]
    assert 'AWS::ECS::Service' not in types and 'AWS::ElasticLoadBalancingV2::Listener' not in types
    assert len(types) == 22
    lb_sg = next(r for r in template['Resources'].values() if r['Type'] == 'AWS::EC2::SecurityGroup'
                 and r['Properties']['GroupDescription'] == 'Web load balancer security group.')
    assert 'SecurityGroupIngress' not in lb_sg['Properties']


@pytest.mark.parametrize('extra', [{}, {'crowdstrike.enabled': True}], ids=['off', 'legacy-enabled'])
def test_appconfig_and_iam_are_unchanged(synthesis_config, synthesize, extra):
    """ The parity inputs never reach AppConfig or IAM; only crowdstrike.enabled (which prod leaves unset)
        has ever added the AppConfig credential stubs, and it still does exactly that. """
    for cls in (C4AppConfig, C4IAM):
        synthesis_config('smaht', 'blue/green', {**SRCE, **CLOSED, **extra})
        base = synthesize(cls)
        synthesis_config('smaht', 'blue/green', {**SRCE, **CLOSED, **extra, **PARITY, 'ecs.indexer.cpu': '1024'})
        assert synthesize(cls) == base


def test_explicit_cid_secret_decouples_from_appconfig_even_with_legacy_switch(synthesis_config, synthesize):
    template = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **FALCON, 'crowdstrike.enabled': True})
    assert 'AppConfigStackNameParameter' not in template['Parameters']
    assert 'AppConfigStackNameParameter' not in str(template)
    # initial-deployment is outside the default scope, so it is not wrapped by the legacy path either
    for key, role, app_name, task in tasks(template, 'blue/green'):
        assert len(task['Properties']['ContainerDefinitions']) == (1 if role == 'initial-deployment' else 2)


def test_legacy_crowdstrike_path_is_unchanged_when_parity_is_off(synthesis_config, synthesize):
    template = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, 'crowdstrike.enabled': True,
                                                                   'splunk.hec_host': 'ignored.example.com'})
    assert 'AppConfigStackNameParameter' in template['Parameters']
    for key, role, app_name, task in tasks(template, 'blue/green'):  # every role, initial included
        names = [c['Name'] for c in task['Properties']['ContainerDefinitions']]
        assert names == [app_name, 'falcon-container']
        assert by_name(task, 'falcon-container')['Environment'] == [{'Name': 'FALCONCTL_OPT_BACKEND', 'Value': 'bpf'}]


@pytest.mark.parametrize('features,expected', [
    (FALCON, ['falcon-container']),
    (SPLUNK, ['splunk-firelens']),
])
def test_each_feature_alone(synthesis_config, synthesize, features, expected):
    template = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **features})
    for key, role, app_name, task in tasks(template, 'blue/green'):
        names = [c['Name'] for c in task['Properties']['ContainerDefinitions']]
        assert names == [app_name] + ([] if role == 'initial-deployment' else expected)
        if role != 'initial-deployment':
            assert len(by_name(task, app_name)['DependsOn']) == 1
            assert ('Volumes' in task['Properties']) == (features is FALCON)


def test_roles_setting_scopes_the_sidecars(synthesis_config, synthesize):
    template = render(synthesis_config, synthesize, 'blue/green',
                      {**CLOSED, **PARITY, 'ecs.observability_roles': '["portal", "initial-deployment"]'})
    for key, role, app_name, task in tasks(template, 'blue/green'):
        count = len(task['Properties']['ContainerDefinitions'])
        assert count == (3 if role in ('portal', 'initial-deployment') else 1), key
        if role == 'initial-deployment':
            assert by_name(task, app_name)['LogConfiguration']['Options']['event_sourcetype'] == \
                'ecs:smaht:initial_deployment_v1'


def test_event_index_and_backend_are_emitted_only_when_set(synthesis_config, synthesize):
    template = render(synthesis_config, synthesize, 'blue/green',
                      {**CLOSED, **PARITY, 'splunk.event_index': 'smaht_prod', 'crowdstrike.backend': 'bpf'})
    for key, role, app_name, task in tasks(template, 'blue/green'):
        if role == 'initial-deployment':
            continue
        assert by_name(task, app_name)['LogConfiguration']['Options']['event_index'] == 'smaht_prod'
        assert by_name(task, 'falcon-container')['Environment'] == [{'Name': 'FALCONCTL_OPT_BACKEND', 'Value': 'bpf'}]


def _indexer_sizes(template):
    return {key: (t['Properties']['Cpu'], t['Properties']['Memory'])
            for key, role, _, t in tasks(template, 'blue/green') if role == 'indexer'}


def test_indexer_sizing_is_honoured_only_with_the_sidecars(synthesis_config, synthesize):
    sizing = {'ecs.indexer.cpu': '1024', 'ecs.indexer.memory': '2048'}
    off = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **sizing})
    assert set(_indexer_sizes(off).values()) == {('256', '512')}  # unchanged legacy behaviour
    on = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **PARITY, **sizing})
    assert set(_indexer_sizes(on).values()) == {('1024', '2048')}
    default = render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **PARITY})
    assert set(_indexer_sizes(default).values()) == {('256', '512')}


@pytest.mark.parametrize('extra,message', [
    ({**PARITY, 'crowdstrike.cid_secret_arn': 'C4AppConfigSmahtProdFalconCID'}, 'crowdstrike.cid_secret_arn'),
    ({**PARITY, 'crowdstrike.sensor_image_digest': None}, 'crowdstrike.sensor_image_digest'),
    ({**PARITY, 'crowdstrike.sensor_image_digest': 'latest'}, 'crowdstrike.sensor_image_digest'),
    ({**PARITY, 'crowdstrike.entrypoint': None}, 'crowdstrike.entrypoint'),
    ({**PARITY, 'splunk.enabled': 'yes'}, 'splunk.enabled'),
    ({**PARITY, 'splunk.hec_host': None}, 'splunk.hec_host'),
    ({**PARITY, 'splunk.hec_host': 'https://http-inputs.example.com:443'}, 'splunk.hec_host'),
    ({**PARITY, 'splunk.hec_token_secret_arn': None}, 'splunk.hec_token_secret_arn'),
    ({**PARITY, 'splunk.firelens_image': 'public.ecr.aws/aws-observability/aws-for-fluent-bit:3'},
     'splunk.firelens_image'),
    ({**PARITY, 'splunk.event_index': 'Prod Index'}, 'splunk.event_index'),
    ({**PARITY, 'ecs.observability_roles': '["portal", "worker"]'}, 'ecs.observability_roles'),
    ({**SPLUNK, 'crowdstrike.enabled': True}, 'cannot be combined'),
])
def test_invalid_inputs_are_rejected(synthesis_config, synthesize, extra, message):
    with pytest.raises((ValueError, RuntimeError), match=message.replace('.', r'\.')):
        render(synthesis_config, synthesize, 'blue/green', {**CLOSED, **extra})
