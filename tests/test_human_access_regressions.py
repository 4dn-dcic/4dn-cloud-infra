"""Adversarial, offline regressions for the human IAM policy contract (not an IAM simulator)."""
import fnmatch
import json
from unittest import mock

import pytest

from src.base import ConfigManager
from src.constants import Settings
from src.parts.iam import C4IAM
from .test_human_access_roles import (
    ALICE, BOB, BOTH_ROLES, BOUNDARY_ID, ENABLED_BOTH, SSO_PRINCIPAL,
    _actions, _allows, _build_template, _flat, _render, _resources, _role, _statements,
)


@pytest.mark.parametrize('setting', [Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS,
                                     Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS])
@pytest.mark.parametrize('value', [
    '*', '123456789012', 'arn:aws:iam::123456789012:root',
    'arn:aws:iam::123456789012:role/*', 'arn:aws:iam::123456789012:user/al?ce',
    'arn:aws:sts::123456789012:assumed-role/Developer/alice',
    'arn:aws:iam::123:user/alice', 'ec2.amazonaws.com',
    'arn:aws-cn:iam::123456789012:role/Developer', [ALICE, 42], True, '[invalid',
    '[__import__("os").getcwd()]',
])
def test_invalid_or_broad_trust_fails_synthesis(setting, value):
    with pytest.raises(ValueError, match='concrete.*IAM user or role ARNs'):
        _build_template(**dict(ENABLED_BOTH, **{setting: value}))


@pytest.mark.parametrize('value', [f' {ALICE}\n{BOB}, {ALICE} ', [ALICE, ' ', BOB, ALICE]])
def test_principal_lists_are_trimmed_and_deduplicated(value):
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: value}))
    trust = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']
    assert trust['Statement'][0]['Principal'] == {'AWS': [ALICE, BOB]}


def test_json_array_principals_survive_real_config_loading(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: [ALICE, BOB]}))
    loaded = ConfigManager._load_config(path)
    assert isinstance(loaded[Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS], str)
    with mock.patch.object(ConfigManager.singleton(), '_get_config', return_value=loaded):
        assert C4IAM._human_access_list(Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS) == [ALICE, BOB]


def test_cross_account_trust_is_explicit_and_sso_paths_are_supported():
    principal = 'arn:aws:iam::999999999999:role/team/ApprovedHuman'
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: [principal, SSO_PRINCIPAL]}))
    trust = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']
    assert trust['Statement'][0]['Principal']['AWS'] == [principal, SSO_PRINCIPAL]
    assert trust['Statement'][0]['Condition']['Bool']['aws:MultiFactorAuthPresent'] == 'true'


def test_oversized_trust_policy_fails_synthesis():
    principals = [f'arn:aws:iam::123456789012:role/team/Operator{n}' for n in range(50)]
    with pytest.raises(ValueError, match='2048-character limit'):
        _build_template(**dict(ENABLED_BOTH, **{Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: principals}))


def test_disabled_features_preserve_the_entire_template_and_ignore_unused_principals():
    with mock.patch.object(C4IAM, 'build_human_access_roles', side_effect=lambda template: template):
        legacy = _build_template()
    assert _build_template() == legacy
    assert _build_template(**{
        Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: 'false',
        Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: '*',
        Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS: ['invalid'],
    }) == legacy
    template = _build_template(**{
        Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: 'true',
        Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: ALICE,
        Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS: '*',
    })
    assert C4IAM.DIAGNOSE_ROLE in template['Resources']
    assert C4IAM.REMEDIATE_ROLE not in template['Resources']


@pytest.mark.parametrize('kms', [False, True])
def test_no_inline_allow_is_nullified_by_an_unconditional_boundary_or_inline_deny(kms):
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: kms}))
    boundary = template['Resources'][BOUNDARY_ID]['Properties']['PolicyDocument']['Statement']
    for role_id in BOTH_ROLES:
        role = _role(template, role_id)
        denies = [s for s in _statements(role) + boundary
                  if s['Effect'] == 'Deny' and 'Condition' not in s]
        for allow in _allows(role):
            for action in _actions(allow):
                for deny in denies:
                    assert not any(fnmatch.fnmatchcase(action.lower(), pattern.lower())
                                   for pattern in _actions(deny)), (role_id, action, deny['Sid'])


@pytest.mark.parametrize('action', ['s3:GetObject', 's3:GetObjectVersion', 's3:ListBucket'])
def test_s3_reads_require_own_account_even_if_a_bucket_policy_grants_access(action):
    template = _build_template(**ENABLED_BOTH)
    role = _role(template, C4IAM.DIAGNOSE_ROLE)
    allowing = [s for s in _allows(role) if action in _actions(s)]
    assert len(allowing) == 1
    assert allowing[0]['Condition'] == {'StringEquals': {'s3:ResourceAccount': {'Ref': 'AWS::AccountId'}}}
    boundary = template['Resources'][BOUNDARY_ID]['Properties']['PolicyDocument']['Statement']
    # Both the inline guardrail and boundary explicitly deny non-local or missing owner context;
    # this is not merely an implicit deny that a grant to an STS session could bypass.
    for statements in (_statements(role), boundary):
        deny = next(s for s in statements if s['Sid'] == 'DenyS3OutsideThisAccount')
        assert deny['Effect'] == 'Deny'
        assert any(fnmatch.fnmatchcase(action, pattern) for pattern in _actions(deny))
        assert deny['Resource'] == ['arn:aws:s3:::*', 'arn:aws:s3:::*/*']
        assert deny['Condition'] == {'StringNotEquals': {'s3:ResourceAccount': {'Ref': 'AWS::AccountId'}}}


@pytest.mark.parametrize('role_id', BOTH_ROLES)
@pytest.mark.parametrize('action, resource', [
    ('ecs:DescribeClusters', 'arn:aws:ecs:<region>:<account-id>:cluster/*'),
    ('ecs:DescribeServices', 'arn:aws:ecs:<region>:<account-id>:service/*'),
    ('ecs:DescribeTasks', 'arn:aws:ecs:<region>:<account-id>:task/*'),
    ('cloudformation:DescribeStacks', 'arn:aws:cloudformation:<region>:<account-id>:stack/*'),
    ('logs:DescribeLogStreams', 'arn:aws:logs:<region>:<account-id>:log-group:*'),
    ('es:DescribeDomain', 'arn:aws:es:<region>:<account-id>:domain/*'),
    ('rds:DescribeDBInstances', 'arn:aws:rds:<region>:<account-id>:db:*'),
    ('states:ListExecutions', 'arn:aws:states:<region>:<account-id>:stateMachine:*'),
])
def test_resource_authorized_inspection_is_not_misclassified_as_wildcard_only(role_id, action, resource):
    role = _role(_build_template(**ENABLED_BOTH), role_id)
    allowing = [s for s in _allows(role) if action in _actions(s)]
    assert len(allowing) == 1
    assert [_render(r) for r in _resources(allowing[0])] == [resource]


def test_stop_query_uses_the_required_wildcard_resource():
    role = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    allowing = [s for s in _allows(role) if 'logs:StopQuery' in _actions(s)]
    assert len(allowing) == 1
    assert allowing[0]['Resource'] == '*'
    assert allowing[0]['Condition']['StringEquals']['aws:RequestedRegion'] == {'Ref': 'AWS::Region'}


@pytest.mark.parametrize('kms', [False, True])
@pytest.mark.parametrize('mfa', [False, True])
def test_enabled_templates_have_valid_local_cloudformation_references(kms, mfa):
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: kms,
        Settings.HUMAN_ACCESS_REQUIRE_MFA: mfa}))

    def check(value):
        if isinstance(value, dict):
            if 'Ref' in value:
                ref = value['Ref']
                assert ref.startswith('AWS::') or ref in template['Resources'], ref
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(template)
    for role_id in BOTH_ROLES:
        role = _role(template, role_id)
        assert 'MultiFactorAuthPresent' not in _flat(role['Policies'])
        trust = role['AssumeRolePolicyDocument']
        assert ('MultiFactorAuthPresent' in _flat(trust)) is mfa
        assert 'DenyAssumeWithoutSourceIdentity' in _flat(trust)


def test_retained_build_delegation_is_not_described_as_a_sandbox():
    from pathlib import Path
    text = (Path(__file__).parents[1] / 'docs/source/human_access_roles.rst').read_text()
    for phrase in ('buildspecOverride', 'RetryBuild', 'service role', 'one-hour', '1800',
                   'not an enforced', 'key policy', 'credentials'):
        assert phrase in text
    role = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    for action in ('codebuild:StartBuild', 'codebuild:RetryBuild'):
        allowing = [s for s in _allows(role) if action in _actions(s)]
        assert len(allowing) == 1
        assert allowing[0]['Condition'] == {'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}
