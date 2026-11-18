""" Backend (ALB -> portal) TLS for the SMaHT SRCE ECS stacks (ecs.backend_tls, ecs.backend_tls_secret_arn).

Asserts on full synthesized templates: the enabled contract (HTTPS target group and health check on
8443, portal-only secret injection, ALB-only task ingress, listener and service wiring), the default
(on when certificate and secret are both configured), the explicit-off fallback (identical to the
certificate-only render), rejection of missing or malformed inputs, the closed bootstrap stage, and
that no other stack or container is touched. Cross-revision parity of the unset/off renders is proven
separately against the pre-change tree (see the PR).
"""
import itertools

import pytest

from src.parts.ecs import C4ECSApplication
from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.fourfront_ecs import FourfrontECSApplication
from src.parts.srce_ecs import C4SRCEECSApplication
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen

CERT = 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000'
SECRET = 'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/portal/nginx-tls-AbC123'
SRCE = {'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1', 'vpc.cidr': '10.10.0.0/16'}
TLS = {'ecs.lb_certificate_arn': CERT, 'ecs.backend_tls_secret_arn': SECRET}

# (class, deployment paradigm, portal container name, portal target-group base names)
VARIANTS = {
    'standalone': (C4SRCEECSApplication, 'standalone', 'portal', ['TargetGroupPortal']),
    'blue/green': (SRCEECSBlueGreen, 'blue/green', 'Portal',
                   ['TargetGroupApplicationBlue', 'TargetGroupApplicationGreen']),
}
PSEUDO = {'AWS::Region', 'AWS::AccountId', 'AWS::StackName', 'AWS::StackId', 'AWS::Partition', 'AWS::URLSuffix',
          'AWS::NoValue', 'AWS::NotificationARNs'}


def render(synthesis_config, synthesize, variant='standalone', extra=None, kind='smaht', srce=True):
    cls, deployment, _, _ = VARIANTS[variant]
    synthesis_config(kind, deployment, {**SRCE, **(extra or {})})
    return synthesize(cls)


def resources(template, rtype):
    return {k: r for k, r in template['Resources'].items() if r['Type'] == rtype}


def containers(template):
    """ (task logical id, container definition) for every container in the template. """
    for key, task in resources(template, 'AWS::ECS::TaskDefinition').items():
        for container in task['Properties']['ContainerDefinitions']:
            yield key, container


def walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def assert_references_resolve(template):
    """ Every Ref/GetAtt/DependsOn names a declared resource or parameter (troposphere does not check). """
    names = set(template['Resources']) | set(template.get('Parameters', {}))
    for node in walk(template):
        if 'Ref' in node:
            assert node['Ref'] in names | PSEUDO, node
        if 'Fn::GetAtt' in node:
            assert node['Fn::GetAtt'][0] in template['Resources'], node
    for key, res in template['Resources'].items():
        depends = res.get('DependsOn', [])
        for dep in [depends] if isinstance(depends, str) else depends:
            assert dep in template['Resources'], (key, dep)


@pytest.mark.parametrize('crowdstrike', [None, 'true'])
@pytest.mark.parametrize('variant', sorted(VARIANTS))
def test_enabled_contract(synthesis_config, synthesize, variant, crowdstrike):
    template = render(synthesis_config, synthesize, variant, {**TLS, 'crowdstrike.enabled': crowdstrike})
    _, _, portal_name, tg_names = VARIANTS[variant]
    assert_references_resolve(template)

    # Target groups: only the new HTTPS groups, with HTTPS health checks on 8443.
    groups = resources(template, 'AWS::ElasticLoadBalancingV2::TargetGroup')
    assert sorted(g['Properties']['Name'] for g in groups.values()) == sorted(f'{n}Https' for n in tg_names)
    for key, group in groups.items():
        props = group['Properties']
        assert key.endswith('Https')
        assert len(props['Name']) <= 32  # ELBv2 target group name limit
        assert (props['Protocol'], props['HealthCheckProtocol'], props['Port']) == ('HTTPS', 'HTTPS', 8443)
        assert (props['HealthCheckPath'], props['Matcher']) == ('/health?format=json', {'HttpCode': '200'})
        assert props['TargetType'] == 'ip'

    # Listeners: HTTPS:443 forwards to the HTTPS group; HTTP:80 only redirects (never forwards plaintext).
    listeners = resources(template, 'AWS::ElasticLoadBalancingV2::Listener')
    assert len(listeners) == 2 * len(tg_names)
    for listener in listeners.values():
        props = listener['Properties']
        (action,) = props['DefaultActions']
        if props['Port'] == 80:
            assert props['Protocol'] == 'HTTP' and action['Type'] == 'redirect'
            assert action['RedirectConfig'] == {'Protocol': 'HTTPS', 'Port': '443', 'StatusCode': 'HTTP_301'}
        else:
            assert (props['Port'], props['Protocol'], action['Type']) == (443, 'HTTPS', 'forward')
            assert props['Certificates'] == [{'CertificateArn': CERT}]
            assert action['TargetGroupArn']['Ref'] in groups

    # Services: the portal services bind container port 8443 to an HTTPS group and wait for the
    # HTTPS (forwarding) listener; indexer/ingester services have no load balancer.
    services = resources(template, 'AWS::ECS::Service')
    portal_services = {k: s for k, s in services.items() if 'LoadBalancers' in s['Properties']}
    assert len(portal_services) == len(tg_names)
    for service in portal_services.values():
        (binding,) = service['Properties']['LoadBalancers']
        assert binding['ContainerName'] == portal_name and binding['ContainerPort'] == 8443
        assert binding['TargetGroupArn']['Ref'] in groups
        (listener,) = service['DependsOn']
        assert listeners[listener]['Properties']['Protocol'] == 'HTTPS'

    # Containers: only the portal application container gets the TLS switch, the two exact JSON-key
    # selectors (as ECS secrets, never environment values) and the single 8443 port mapping.
    portal_tasks = 0
    for task, container in containers(template):
        env = {e['Name']: e['Value'] for e in container.get('Environment', [])}
        secrets = {s['Name']: s['ValueFrom'] for s in container.get('Secrets', [])}
        if container['Name'] == portal_name:
            portal_tasks += 1
            assert env['NGINX_TLS_ENABLED'] == 'true'
            assert {k: v for k, v in secrets.items() if k.startswith('NGINX_')} == {
                'NGINX_SSL_CERTIFICATE': f'{SECRET}:NGINX_SSL_CERTIFICATE::',
                'NGINX_SSL_CERTIFICATE_KEY': f'{SECRET}:NGINX_SSL_CERTIFICATE_KEY::',
            }
            assert container['PortMappings'] == [{'ContainerPort': 8443}]
        else:
            assert not any(name.startswith('NGINX_') for name in [*env, *secrets]), (task, container['Name'])
            assert SECRET not in str(container)
    assert portal_tasks == len(tg_names)

    # Task ingress: only 8443, only from the ALB security group (no VPC CIDR, no 8000).
    (lb_sg,) = [k for k in resources(template, 'AWS::EC2::SecurityGroup') if k.endswith('LBSecurityGroup')]
    (task_sg,) = [s for k, s in resources(template, 'AWS::EC2::SecurityGroup').items()
                  if k.endswith('ContainerSecurityGroup')]
    assert task_sg['Properties']['SecurityGroupIngress'] == [
        {'IpProtocol': 'tcp', 'FromPort': 8443, 'ToPort': 8443, 'SourceSecurityGroupId': {'Ref': lb_sg}}]
    assert task_sg['Properties']['GroupDescription'] == 'Container Security Group.'


@pytest.mark.parametrize('variant', sorted(VARIANTS))
@pytest.mark.parametrize('setting', [None, 'true', 'True', ' TRUE '])
def test_default_on_and_explicit_true_are_the_same(synthesis_config, synthesize, variant, setting):
    baseline = render(synthesis_config, synthesize, variant, TLS)
    assert render(synthesis_config, synthesize, variant, {**TLS, 'ecs.backend_tls': setting}) == baseline


@pytest.mark.parametrize('variant', sorted(VARIANTS))
@pytest.mark.parametrize('setting', ['false', 'False', 'FALSE'])
@pytest.mark.parametrize('secret', [None, SECRET])
def test_explicit_off_is_the_certificate_only_render(synthesis_config, synthesize, variant, setting, secret):
    """ The fallback: identical to the existing certificate-only stack -- browser HTTPS and the :80
        redirect kept, HTTP target group/health check and port on the ALB -> task hop. """
    cert_only = render(synthesis_config, synthesize, variant, {'ecs.lb_certificate_arn': CERT})
    fallback = render(synthesis_config, synthesize, variant, {
        'ecs.lb_certificate_arn': CERT, 'ecs.backend_tls_secret_arn': secret, 'ecs.backend_tls': setting})
    assert fallback == cert_only
    for group in resources(fallback, 'AWS::ElasticLoadBalancingV2::TargetGroup').values():
        assert group['Properties']['Protocol'] == 'HTTP'
    ports = {listener['Properties']['Port']: listener['Properties']['DefaultActions'][0]['Type']
             for listener in resources(fallback, 'AWS::ElasticLoadBalancingV2::Listener').values()}
    assert ports == {80: 'redirect', 443: 'forward'}
    assert 'NGINX_' not in str(fallback)


@pytest.mark.parametrize('variant', sorted(VARIANTS))
@pytest.mark.parametrize('certificate', [None, CERT])
def test_no_secret_is_the_legacy_render(synthesis_config, synthesize, variant, certificate):
    legacy = render(synthesis_config, synthesize, variant, {'ecs.lb_certificate_arn': certificate})
    assert 'NGINX_' not in str(legacy) and 'Https' not in str(legacy)


@pytest.mark.parametrize('variant', sorted(VARIANTS))
@pytest.mark.parametrize('extra, missing', [
    ({'ecs.backend_tls': 'true'}, ['ecs.backend_tls_secret_arn', 'ecs.lb_certificate_arn']),
    ({'ecs.backend_tls': 'true', 'ecs.lb_certificate_arn': CERT}, ['ecs.backend_tls_secret_arn']),
    ({'ecs.backend_tls': 'true', 'ecs.backend_tls_secret_arn': SECRET}, ['ecs.lb_certificate_arn']),
    # Unset, secret without certificate: an error rather than a quiet HTTP backend.
    ({'ecs.backend_tls_secret_arn': SECRET}, ['ecs.lb_certificate_arn']),
])
def test_missing_inputs_are_rejected(synthesis_config, synthesize, variant, extra, missing):
    with pytest.raises(ValueError, match='Backend TLS') as error:
        render(synthesis_config, synthesize, variant, extra)
    for name in missing:
        assert f'{name} is not set' in str(error.value)


@pytest.mark.parametrize('variant', sorted(VARIANTS))
@pytest.mark.parametrize('extra', [TLS, {**TLS, 'ecs.backend_tls': 'true'}])
def test_only_smaht_may_enable_it(synthesis_config, synthesize, variant, extra):
    with pytest.raises(ValueError, match="only for app.kind 'smaht', not 'cgap'"):
        render(synthesis_config, synthesize, variant, extra, kind='cgap')
    # ...while the explicit fallback renders the non-SMaHT stack exactly as without any input.
    plain = render(synthesis_config, synthesize, variant, {'ecs.lb_certificate_arn': CERT}, kind='cgap')
    assert render(synthesis_config, synthesize, variant, {**TLS, 'ecs.backend_tls': 'false'}, kind='cgap') == plain


@pytest.mark.parametrize('value', ['yes', '1', '0', 'on', 'ture', '[]'])
def test_invalid_setting_is_rejected(synthesis_config, synthesize, value):
    with pytest.raises(ValueError, match='ecs.backend_tls must be true or false'):
        render(synthesis_config, synthesize, extra={**TLS, 'ecs.backend_tls': value})


@pytest.mark.parametrize('arn', [
    'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/portal/nginx-tls',  # no suffix
    f'{SECRET}:NGINX_SSL_CERTIFICATE::',  # a selector already appended
    'arn:aws:secretsmanager:us-east-1:123456789012:secret:nginx-tls-AbC12',  # 5-character suffix
    'arn:aws:ssm:us-east-1:123456789012:parameter/nginx-tls-AbC123',
    'smaht-test/portal/nginx-tls',
    'true',
])
@pytest.mark.parametrize('setting', [None, 'false'])
def test_malformed_secret_arn_is_rejected(synthesis_config, synthesize, arn, setting):
    with pytest.raises(ValueError, match='ecs.backend_tls_secret_arn must be the complete'):
        render(synthesis_config, synthesize, extra={'ecs.lb_certificate_arn': CERT,
                                                    'ecs.backend_tls_secret_arn': arn, 'ecs.backend_tls': setting})


@pytest.mark.parametrize('cls, kind, deployment', [
    (cls, kind, deployment)
    for (cls, deployment), kind in itertools.product(
        [(C4ECSApplication, 'standalone'), (ECSBlueGreen, 'blue/green'), (FourfrontECSApplication, 'standalone')],
        ['cgap', 'smaht', 'ff'])
])
def test_non_srce_stacks_ignore_the_settings(synthesis_config, synthesize, cls, kind, deployment):
    """ The settings are SRCE-only: the shared classes (fixed Fourfront/CGAP/SMaHT stacks) render
        identically whatever they say, even invalid values. """
    synthesis_config(kind, deployment, {'ecs.lb_certificate_arn': CERT})
    baseline = synthesize(cls)
    for extra in [TLS, {**TLS, 'ecs.backend_tls': 'true'}, {'ecs.backend_tls': 'nonsense',
                                                            'ecs.backend_tls_secret_arn': 'not-an-arn'}]:
        synthesis_config(kind, deployment, {'ecs.lb_certificate_arn': CERT, **extra})
        assert synthesize(cls) == baseline


def test_closed_bootstrap_stays_closed_and_selects_tls_from_the_secret(synthesis_config, synthesize):
    """ In the closed stage (no listeners, so no certificate needed yet) the secret alone selects backend
        TLS; the stage stays closed, and leaving it by adding the certificate keeps every permanent
        resource, including the HTTPS target groups. """
    closed = render(synthesis_config, synthesize, 'blue/green',
                    {'ecs.bootstrap_closed': 'true', 'ecs.backend_tls_secret_arn': SECRET})
    assert_references_resolve(closed)
    counts = {}
    for res in closed['Resources'].values():
        counts[res['Type']] = counts.get(res['Type'], 0) + 1
    assert counts == {
        'AWS::EC2::SecurityGroup': 2, 'AWS::ElasticLoadBalancingV2::LoadBalancer': 2,
        'AWS::ElasticLoadBalancingV2::TargetGroup': 2, 'AWS::ECS::Cluster': 2,
        'AWS::ECS::TaskDefinition': 10, 'AWS::CloudWatch::Alarm': 4,
    }
    (lb_sg,) = [r for k, r in closed['Resources'].items() if k.endswith('LBSecurityGroup')]
    assert 'SecurityGroupIngress' not in lb_sg['Properties']
    for group in resources(closed, 'AWS::ElasticLoadBalancingV2::TargetGroup').values():
        assert group['Properties']['Protocol'] == 'HTTPS'
    # Explicit true is also allowed in the closed stage without the certificate.
    assert render(synthesis_config, synthesize, 'blue/green', {
        'ecs.bootstrap_closed': 'true', 'ecs.backend_tls_secret_arn': SECRET, 'ecs.backend_tls': 'true'}) == closed

    opened = render(synthesis_config, synthesize, 'blue/green', TLS)
    closed_res, opened_res = closed['Resources'], opened['Resources']
    assert set(closed_res) <= set(opened_res)
    added = {opened_res[k]['Type'] for k in set(opened_res) - set(closed_res)}
    assert added == {'AWS::ECS::Service', 'AWS::ElasticLoadBalancingV2::Listener'}
    for key, res in closed_res.items():
        if key.endswith('LBSecurityGroup'):
            assert {p for p in set(res['Properties']) | set(opened_res[key]['Properties'])
                    if res['Properties'].get(p) != opened_res[key]['Properties'].get(p)} == {'SecurityGroupIngress'}
        else:
            assert opened_res[key] == res, key


@pytest.mark.parametrize('variant', sorted(VARIANTS))
def test_switching_modes_never_reuses_a_target_group_identity(synthesis_config, synthesize, variant):
    """ A target group's protocol cannot change in place and its physical name is fixed, so the two modes
        use disjoint target groups: switching adds one and removes the other instead of attempting an
        impossible same-name replacement. Every other permanent resource keeps its logical id. """
    on = render(synthesis_config, synthesize, variant, TLS)
    off = render(synthesis_config, synthesize, variant, {**TLS, 'ecs.backend_tls': 'false'})
    on_groups = resources(on, 'AWS::ElasticLoadBalancingV2::TargetGroup')
    off_groups = resources(off, 'AWS::ElasticLoadBalancingV2::TargetGroup')
    assert not set(on_groups) & set(off_groups)
    assert not ({g['Properties']['Name'] for g in on_groups.values()}
                & {g['Properties']['Name'] for g in off_groups.values()})
    assert set(on['Resources']) - set(on_groups) == set(off['Resources']) - set(off_groups)
