""" Opt-in declarative S3-encryption-key access for Tibanna tiger roles (datastore.tibanna_tiger_env).

tibanna_smaht's deploy_tiger otherwise grants its roles key use by rewriting the CloudFormation-managed key policy
with PutKeyPolicy (out-of-band drift). The setting appends one statement naming exactly that env's seven roles; the
existing statements and every other resource must be untouched.
"""
import pytest

from src.parts.srce_datastore import C4SRCEDatastore

SRCE = {'db.vpc.id': 'vpc-0bbbbbbbbbbbbbbb1', 'db.vpc.cidr': '10.20.0.0/16'}
ROLES = ['for_ec2', 'states', 'run_task', 'check_task', 'start_run', 'update_ffmeta', 'update_cost']


def render(synthesis_config, synthesize, extra=None):
    synthesis_config('smaht', 'blue/green', {**SRCE, **(extra or {})})
    return synthesize(C4SRCEDatastore)


def key_policy(template):
    (key,) = [r for r in template['Resources'].values() if r['Type'] == 'AWS::KMS::Key']
    return key['Properties']['KeyPolicy']


@pytest.mark.parametrize('value', [None, ''])
def test_unset_is_unchanged(synthesis_config, synthesize, value):
    """ Unset (or empty, which the config layer treats as unset) keeps the three existing statements only. """
    baseline = render(synthesis_config, synthesize, {'datastore.tibanna_tiger_env': value})
    assert [s['Sid'] for s in key_policy(baseline)['Statement']] == [
        'Enable Admin IAM Policies', 'Allow use of the key', 'Allow SRCE S3 upload role to use the key']


def test_grant_is_one_appended_statement(synthesis_config, synthesize):
    baseline = render(synthesis_config, synthesize)
    granted = render(synthesis_config, synthesize, {'datastore.tibanna_tiger_env': 'smaht-prod-srce'})
    # Only the key's KeyPolicy differs, and only by an appended statement.
    changed = [k for k in baseline['Resources'] if baseline['Resources'][k] != granted['Resources'][k]]
    assert set(baseline['Resources']) == set(granted['Resources'])
    assert len(changed) == 1 and granted['Resources'][changed[0]]['Type'] == 'AWS::KMS::Key'
    before, after = key_policy(baseline), key_policy(granted)
    assert after['Statement'][:-1] == before['Statement']
    assert {k: v for k, v in after.items() if k != 'Statement'} == {k: v for k, v in before.items() if k != 'Statement'}
    for section in ('Parameters', 'Outputs'):
        assert granted.get(section) == baseline.get(section)
    statement = after['Statement'][-1]
    assert statement['Sid'] == 'Allow Tibanna tiger roles to use the key'
    assert statement['Principal'] == {'AWS': '*'} and statement['Resource'] == '*'
    assert statement['Action'] == ['kms:Encrypt', 'kms:Decrypt', 'kms:ReEncrypt*', 'kms:GenerateDataKey*',
                                   'kms:DescribeKey']
    # Exact role ARNs (no wildcard), in this account.
    arns = statement['Condition']['ArnEquals']['aws:PrincipalArn']
    assert [a['Fn::Join'][1][2] for a in arns] == [f':role/tibanna_tiger_smaht-prod-srce_{r}' for r in ROLES]
    assert all(a['Fn::Join'][1][:2] == ['arn:aws:iam::', {'Ref': 'AWS::AccountId'}] for a in arns)
    assert '*' not in ''.join(a['Fn::Join'][1][2] for a in arns)


@pytest.mark.parametrize('env', [' ', 'bad env', 'env/with/slash', '*', 'x' * 40])
def test_invalid_env_is_rejected(synthesis_config, synthesize, env):
    with pytest.raises(ValueError, match='datastore.tibanna_tiger_env'):
        render(synthesis_config, synthesize, {'datastore.tibanna_tiger_env': env})
