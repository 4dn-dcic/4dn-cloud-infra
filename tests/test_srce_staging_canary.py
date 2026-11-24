""" The opt-in staging canary of the SRCE blue/green ECS stack (ecs.staging_canary).

The canary opens blue (staging) alone, with explicit minimal service counts, while green (data) keeps
no service and no listener, and the shared ALB security group admits 443/80 only from one validated
source: a managed prefix list id or a list of public CIDRs. These tests assert on the full synthesized
template against the closed bootstrap stage it is entered from.
"""
import pytest

from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen

CERT = 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000'
SRCE = {'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1', 'vpc.cidr': '10.10.0.0/16'}
PREFIX_LIST = 'pl-0123456789abcdef0'
CANARY = {'ecs.bootstrap_closed': 'false', 'ecs.staging_canary': 'true', 'ecs.lb_certificate_arn': CERT,
          'ecs.staging_canary_source_prefix_list': PREFIX_LIST}
CLOSED = {'ecs.bootstrap_closed': 'true', 'ecs.lb_certificate_arn': CERT}


def render(synthesis_config, synthesize, extra=None, kind='smaht', cls=SRCEECSBlueGreen):
    synthesis_config(kind, 'blue/green', {**SRCE, **(extra or {})})
    return synthesize(cls)


def of_type(template, resource_type):
    return {k: r for k, r in template['Resources'].items() if r['Type'] == resource_type}


def lb_ingress(template):
    (sg,) = [r['Properties'] for k, r in template['Resources'].items()
             if r['Type'] == 'AWS::EC2::SecurityGroup' and k.endswith('LBSecurityGroup')]
    return sg.get('SecurityGroupIngress')


@pytest.mark.parametrize('kind', ['cgap', 'smaht'])
def test_canary_opens_blue_only(synthesis_config, synthesize, kind):
    template = render(synthesis_config, synthesize, CANARY, kind=kind)
    services = of_type(template, 'AWS::ECS::Service')
    assert len(services) == 3
    for key, service in services.items():
        assert 'blue' in key and 'green' not in key
        assert service['Properties']['Cluster'] == {'Ref': f'{kind.capitalize()}Testblue'}
        assert service['Properties']['DesiredCount'] == 1  # explicit, not a template default
        # The capacity provider Base follows the count instead of the production default of 8/4.
        assert max(item['Base'] for item in service['Properties']['CapacityProviderStrategy']) == 1
    listeners = of_type(template, 'AWS::ElasticLoadBalancingV2::Listener')
    assert sorted(listeners) == ['C4SRCEEcsBlueGreenMainLBHTTPSListenerblue',
                                 'C4SRCEEcsBlueGreenMainLBListenerblue']
    for listener in listeners.values():
        assert listener['Properties']['LoadBalancerArn'] == {'Ref': 'C4SRCEEcsBlueGreenMainblueLoadBalancer'}
    (https,) = [lsn['Properties'] for lsn in listeners.values() if lsn['Properties']['Port'] == 443]
    assert https['Protocol'] == 'HTTPS' and https['Certificates'] == [{'CertificateArn': CERT}]


def test_canary_ingress_is_the_prefix_list_only(synthesis_config, synthesize):
    ingress = lb_ingress(render(synthesis_config, synthesize, CANARY))
    assert ingress == [
        {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'SourcePrefixListId': PREFIX_LIST},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'SourcePrefixListId': PREFIX_LIST},
    ]


def test_canary_ingress_from_cidrs(synthesis_config, synthesize):
    extra = {**CANARY, 'ecs.staging_canary_source_prefix_list': None,
             'ecs.staging_canary_source_cidrs': "['198.51.100.7/32', '203.0.113.9/32', '2001:db8::/32']"}
    ingress = lb_ingress(render(synthesis_config, synthesize, extra))
    assert ingress == [
        {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'CidrIp': '198.51.100.7/32'},
        {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'CidrIp': '203.0.113.9/32'},
        {'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'CidrIpv6': '2001:db8::/32'},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'CidrIp': '198.51.100.7/32'},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'CidrIp': '203.0.113.9/32'},
        {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'CidrIpv6': '2001:db8::/32'},
    ]
    assert not any(rule.get('CidrIp') == '0.0.0.0/0' for rule in ingress)


@pytest.mark.parametrize('backend_tls', [{}, {'ecs.backend_tls_secret_arn': (
        'arn:aws:secretsmanager:us-east-1:123456789012:secret:smaht-test/portal/nginx-tls-AbCdEf')}])
def test_transition_from_closed_only_adds_blue_and_restricts_ingress(synthesis_config, synthesize, backend_tls):
    """ From the closed stage the canary adds only blue's listeners and services and changes only the
        ALB security group's ingress in place: no replacement, no task definition change, nothing for
        green. Backend TLS (when configured) carries over unchanged. """
    closed = render(synthesis_config, synthesize, {**CLOSED, **backend_tls})
    canary = render(synthesis_config, synthesize, {**CANARY, **backend_tls})
    closed_res, canary_res = closed['Resources'], canary['Resources']
    assert set(closed_res) <= set(canary_res)
    added = set(canary_res) - set(closed_res)
    assert {canary_res[k]['Type'] for k in added} == {'AWS::ECS::Service', 'AWS::ElasticLoadBalancingV2::Listener'}
    assert len(added) == 5 and all('blue' in k for k in added)
    for key, res in closed_res.items():
        if key.endswith('LBSecurityGroup'):
            changed = {p for p in set(res['Properties']) | set(canary_res[key]['Properties'])
                       if res['Properties'].get(p) != canary_res[key]['Properties'].get(p)}
            assert changed == {'SecurityGroupIngress'}
        else:
            assert canary_res[key] == res, key
    if backend_tls:
        (portal,) = [s for s in of_type(canary, 'AWS::ECS::Service').values() if 'LoadBalancers' in s['Properties']]
        assert portal['Properties']['LoadBalancers'][0]['ContainerPort'] == 8443


def test_canary_off_is_unchanged(synthesis_config, synthesize):
    """ Unset/false renders exactly the closed or normal stack, as before. """
    for base in (CLOSED, {'ecs.lb_certificate_arn': CERT}):
        assert (render(synthesis_config, synthesize, {**base, 'ecs.staging_canary': 'false'})
                == render(synthesis_config, synthesize, base))


@pytest.mark.parametrize('extra, match', [
    ({'ecs.staging_canary_source_prefix_list': None}, 'exactly one source'),
    ({'ecs.staging_canary_source_cidrs': '198.51.100.7/32'}, 'exactly one source'),
    ({'ecs.staging_canary_source_prefix_list': 'pl-123'}, 'not a managed prefix list id'),
    ({'ecs.staging_canary_source_prefix_list': 'sg-0511b657820392ed0'}, 'not a managed prefix list id'),
    ({'ecs.staging_canary_source_prefix_list': None, 'ecs.staging_canary_source_cidrs': '0.0.0.0/0'},
     'matches every address'),
    ({'ecs.staging_canary_source_prefix_list': None, 'ecs.staging_canary_source_cidrs': '10.124.0.0/16'},
     'not a public address range'),
    ({'ecs.staging_canary_source_prefix_list': None, 'ecs.staging_canary_source_cidrs': '198.51.100.7/24'},
     'not a valid CIDR'),
    ({'ecs.staging_canary_source_prefix_list': None, 'ecs.staging_canary_source_cidrs': '[]'}, 'empty entry'),
    ({'ecs.bootstrap_closed': 'true'}, 'both true'),
    ({'ecs.lb_certificate_arn': None}, 'needs ecs.lb_certificate_arn'),
    ({'ecs.wsgi.count': '8'}, 'fixed explicit service counts'),
    ({'ecs.indexer.count': '4'}, 'fixed explicit service counts'),
    ({'ecs.staging_canary': 'yes'}, 'must be true or false'),
])
def test_invalid_canary_config_is_rejected(synthesis_config, synthesize, extra, match):
    with pytest.raises(ValueError, match=match):
        render(synthesis_config, synthesize, {**CANARY, **extra})


@pytest.mark.parametrize('stray', ['ecs.staging_canary_source_prefix_list', 'ecs.staging_canary_source_cidrs'])
@pytest.mark.parametrize('base', [CLOSED, {'ecs.lb_certificate_arn': CERT}])
def test_source_without_canary_is_rejected(synthesis_config, synthesize, stray, base):
    """ A source left configured while the canary is off would read as restricted while the normal
        stack admits 0.0.0.0/0, so it is an error. """
    value = PREFIX_LIST if stray.endswith('prefix_list') else '198.51.100.7/32'
    with pytest.raises(ValueError, match='only applies with ecs.staging_canary'):
        render(synthesis_config, synthesize, {**base, stray: value})


@pytest.mark.parametrize('kind', ['cgap', 'smaht'])
def test_non_srce_blue_green_ignores_the_setting(synthesis_config, synthesize, kind):
    """ The canary is SRCE-only: the shared blue/green class renders identically whatever its settings
        say (the certificate, which that class does honour, is set on both sides). """
    synthesis_config(kind, 'blue/green', {'ecs.lb_certificate_arn': CERT})
    baseline = synthesize(ECSBlueGreen)
    synthesis_config(kind, 'blue/green', {**CANARY})
    assert synthesize(ECSBlueGreen) == baseline
