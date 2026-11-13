""" The opt-in closed bootstrap stage of the SRCE blue/green ECS stack (ecs.bootstrap_closed).

The stage exists so the permanent ALBs (and so their AWS DNS names) can be created before any
hostname, certificate or application configuration exists, without anything being able to connect
to them or start an application task. These tests assert on the full synthesized template, and on
the later transition to the normal stack keeping every permanent resource's identity.
"""
import pytest

from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen

CERT = 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000'
SRCE = {'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1', 'vpc.cidr': '10.10.0.0/16'}

# Every resource type that can create or start ECS tasks, or scale/schedule them.
TASK_STARTING_TYPES = {
    'AWS::ECS::Service', 'AWS::ECS::TaskSet',
    'AWS::ApplicationAutoScaling::ScalableTarget', 'AWS::ApplicationAutoScaling::ScalingPolicy',
    'AWS::Events::Rule', 'AWS::Scheduler::Schedule', 'AWS::Pipes::Pipe',
    'AWS::StepFunctions::StateMachine', 'AWS::Lambda::Function',
}
PERMANENT_TYPES = {
    'AWS::EC2::SecurityGroup', 'AWS::ElasticLoadBalancingV2::LoadBalancer',
    'AWS::ElasticLoadBalancingV2::TargetGroup', 'AWS::ECS::Cluster',
}


def by_type(template):
    out = {}
    for key, res in template['Resources'].items():
        out.setdefault(res['Type'], {})[key] = res
    return out


def lb_security_group(template):
    (sg,) = [res['Properties'] for key, res in template['Resources'].items()
             if res['Type'] == 'AWS::EC2::SecurityGroup' and key.endswith('LBSecurityGroup')]
    return sg


def render(synthesis_config, synthesize, kind='smaht', extra=None, cls=SRCEECSBlueGreen):
    synthesis_config(kind, 'blue/green', {**SRCE, **(extra or {})})
    return synthesize(cls)


@pytest.mark.parametrize('kind', ['cgap', 'smaht'])
@pytest.mark.parametrize('certificate', [None, CERT])
def test_closed_stage_template(synthesis_config, synthesize, kind, certificate):
    template = render(synthesis_config, synthesize, kind,
                      {'ecs.bootstrap_closed': 'true', 'ecs.lb_certificate_arn': certificate})
    types = by_type(template)
    counts = {t: len(r) for t, r in types.items()}
    assert counts == {
        'AWS::EC2::SecurityGroup': 2, 'AWS::ElasticLoadBalancingV2::LoadBalancer': 2,
        'AWS::ElasticLoadBalancingV2::TargetGroup': 2, 'AWS::ECS::Cluster': 2,
        'AWS::ECS::TaskDefinition': 10, 'AWS::CloudWatch::Alarm': 4,
    }
    assert sum(counts.values()) == 22
    assert not set(types) & TASK_STARTING_TYPES
    assert 'AWS::ElasticLoadBalancingV2::Listener' not in types
    # No ingress at all on the ALB security group.
    assert 'SecurityGroupIngress' not in lb_security_group(template)
    # Alarms are informational only: nothing they could trigger.
    for alarm in types['AWS::CloudWatch::Alarm'].values():
        assert not alarm['Properties'].get('AlarmActions')
    # Nothing in the template references a listener or service (e.g. a dangling DependsOn).
    for res in template['Resources'].values():
        assert 'DependsOn' not in res
    # Outputs are the bare ALB DNS names (nothing is served, so no URL scheme).
    assert len(template['Outputs']) == 2
    for output in template['Outputs'].values():
        joined = output['Value']['Fn::Join'][1]
        assert joined[0] == ''
        assert joined[1]['Fn::GetAtt'][1] == 'DNSName'


@pytest.mark.parametrize('value', [None, 'false', 'False', 'FALSE'])
@pytest.mark.parametrize('certificate', [None, CERT])
def test_unset_or_false_is_the_normal_stack(synthesis_config, synthesize, value, certificate):
    baseline = render(synthesis_config, synthesize, extra={'ecs.lb_certificate_arn': certificate})
    configured = render(synthesis_config, synthesize,
                        extra={'ecs.bootstrap_closed': value, 'ecs.lb_certificate_arn': certificate})
    assert configured == baseline
    types = by_type(baseline)
    assert len(types['AWS::ECS::Service']) == 6
    assert len(types['AWS::ElasticLoadBalancingV2::Listener']) == (4 if certificate else 2)
    ports = sorted(rule['FromPort'] for rule in lb_security_group(baseline)['SecurityGroupIngress'])
    assert ports == [80, 443]


@pytest.mark.parametrize('value', ['true', 'True', ' TRUE '])
def test_true_spellings(synthesis_config, synthesize, value):
    template = render(synthesis_config, synthesize, extra={'ecs.bootstrap_closed': value})
    assert 'AWS::ECS::Service' not in by_type(template)


@pytest.mark.parametrize('value', ['yes', '1', '0', 'ture', 'on', '[]'])
def test_invalid_value_is_rejected(synthesis_config, synthesize, value):
    with pytest.raises(ValueError, match='ecs.bootstrap_closed'):
        render(synthesis_config, synthesize, extra={'ecs.bootstrap_closed': value})


@pytest.mark.parametrize('kind', ['cgap', 'smaht'])
def test_non_srce_blue_green_ignores_the_setting(synthesis_config, synthesize, kind):
    """ The setting is SRCE-only: the shared blue/green class (fixed Fourfront/CGAP/SMaHT stacks)
        renders identically whatever it says, even an invalid value. """
    synthesis_config(kind, 'blue/green')
    baseline = synthesize(ECSBlueGreen)
    for value in ['true', 'nonsense']:
        synthesis_config(kind, 'blue/green', {'ecs.bootstrap_closed': value})
        assert synthesize(ECSBlueGreen) == baseline


@pytest.mark.parametrize('certificate', [None, CERT])
def test_transition_to_normal_keeps_permanent_identities(synthesis_config, synthesize, certificate):
    """ Leaving the bootstrap stage (with or without a certificate) only adds listeners and services
        and opens the existing ALB security group; every bootstrap resource keeps its logical id and
        immutable properties, so CloudFormation updates rather than replaces it. """
    closed = render(synthesis_config, synthesize, extra={'ecs.bootstrap_closed': 'true'})
    normal = render(synthesis_config, synthesize, extra={'ecs.lb_certificate_arn': certificate})
    closed_res, normal_res = closed['Resources'], normal['Resources']
    assert set(closed_res) <= set(normal_res)
    added = {normal_res[k]['Type'] for k in set(normal_res) - set(closed_res)}
    assert added == {'AWS::ECS::Service', 'AWS::ElasticLoadBalancingV2::Listener'}
    for key, res in closed_res.items():
        if key.endswith('LBSecurityGroup'):
            changed = {p for p in set(res['Properties']) | set(normal_res[key]['Properties'])
                       if res['Properties'].get(p) != normal_res[key]['Properties'].get(p)}
            assert changed == {'SecurityGroupIngress'}  # in-place update, no replacement
        else:
            assert normal_res[key] == res, key
    for key, res in closed_res.items():
        if res['Type'] in PERMANENT_TYPES:
            assert normal_res[key]['Type'] == res['Type']
    lbs = [res['Properties'] for res in closed_res.values()
           if res['Type'] == 'AWS::ElasticLoadBalancingV2::LoadBalancer']
    assert sorted(lb['Name'] for lb in lbs) == ['smaht-testblue', 'smaht-testgreen']
    assert all(lb['Scheme'] == 'internet-facing' for lb in lbs)
    assert set(closed['Outputs']) == set(normal['Outputs'])
