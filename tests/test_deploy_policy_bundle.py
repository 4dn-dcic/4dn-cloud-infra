"""
Offline tests for the account-specific deployment policy bundle in
docs/examples/smaht-deployment-manager-517723527581-us-east-1/ (IAM Identity Center permission set
SMaHT-Deployment-Manager): reproducible from the generator, identical to the opt-in role's
documents for that account and Region, standalone valid IAM JSON with nothing left to fill in, and
within the IAM / IAM Identity Center quotas.
"""
import io
import json
import os
import re
import shutil

import pytest

from src.commands import render_deploy_policy_bundle as bundle
from .test_human_deploy_role import (
    BUNDLE, BUNDLE_DIR, REFERENCE, REPO_ROOT, _decide, _deploy_documents, _deploy_template,
)

ACCOUNT, REGION = BUNDLE['account_id'], BUNDLE['region']
MANAGED = BUNDLE['customer_managed_policies']
INLINE = BUNDLE['inline_policy']
GENERATED_FILES = [entry['file'] for entry in MANAGED] + [INLINE['file'], bundle.MANIFEST]
ARGS = ['--account-id', ACCOUNT, '--region', REGION, '--permission-set', BUNDLE['permission_set'],
        '--policy-prefix', 'SMaHT', '--out', os.path.relpath(BUNDLE_DIR, REPO_ROOT)]


def _document(name):
    return json.load(io.open(os.path.join(BUNDLE_DIR, name)))


def _documents():
    return [_document(entry['file']) for entry in MANAGED] + [_document(INLINE['file'])]


def _statements():
    return [statement for document in _documents() for statement in document['Statement']]


def test_bundle_target_and_layout():
    assert (ACCOUNT, REGION, BUNDLE['permission_set']) == ('517723527581', 'us-east-1', 'SMaHT-Deployment-Manager')
    assert [entry['name'] for entry in MANAGED] == [
        'SMaHTInfraDeployStackPolicy', 'SMaHTInfraDeployComputePolicy', 'SMaHTInfraDeployDataPolicy',
        'SMaHTInfraDeployTibannaPolicy']
    assert all(entry['path'] == '/' and entry['file'] == entry['name'] + '.json' for entry in MANAGED)
    assert BUNDLE['aws_managed_policies'] == []
    assert sorted(os.listdir(BUNDLE_DIR)) == sorted(GENERATED_FILES + ['README.md'])


def test_bundle_is_exactly_what_the_generator_renders(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)  # --out in the manifest is relative to the repository
    files = bundle.render_bundle(account_id=ACCOUNT, region=REGION, permission_set=BUNDLE['permission_set'],
                                 policy_prefix='SMaHT', out=ARGS[-1])
    assert sorted(files) == sorted(GENERATED_FILES)
    for name, text in files.items():
        assert io.open(os.path.join(BUNDLE_DIR, name)).read() == text, name
    assert bundle.main(ARGS + ['--check']) == bundle.EXIT_OK


def test_bundle_documents_equal_the_opt_in_roles_documents_for_this_account_and_region():
    """ Parity with the CloudFormation-rendered role (its four managed policies, then its inline
        guardrail), not just with the function that feeds it.
    """
    role_documents = [bundle.materialize(document, ACCOUNT, REGION)
                      for _, document in _deploy_documents(_deploy_template())]
    assert role_documents == _documents()


def test_bundle_documents_are_standalone_iam_policies():
    sids = []
    for document in _documents():
        assert set(document) == {'Version', 'Statement'} and document['Version'] == '2012-10-17'
        for statement in document['Statement']:
            assert set(statement) <= {'Sid', 'Effect', 'Action', 'NotAction', 'Resource', 'NotResource',
                                      'Condition'}
            assert statement['Effect'] in ('Allow', 'Deny')
            assert ('Action' in statement) != ('NotAction' in statement)
            assert ('Resource' in statement) != ('NotResource' in statement)
            sids.append(statement['Sid'])
    assert len(sids) == len(set(sids))
    allows = [d for d in _documents()[:-1] for s in d['Statement'] if s['Effect'] != 'Allow']
    denies = [s for s in _documents()[-1]['Statement'] if s['Effect'] != 'Deny']
    assert not allows and not denies  # managed = allow documents, inline = deny-only guardrail


def test_bundle_has_no_unresolved_values_and_only_its_account_and_region():
    for name in GENERATED_FILES[:-1]:
        text = io.open(os.path.join(BUNDLE_DIR, name)).read()
        for marker in ('<', '>', '${', '{{', '"Ref"', 'Fn::', 'AWS::', 'PLACEHOLDER', 'XXX', 'TODO'):
            assert marker not in text, (name, marker)
        assert set(re.findall(r'\b\d{12}\b', text)) == {ACCOUNT}, name
        for arn in re.findall(r'arn:aws:[^"]+', text):
            _, _, service, region, account = arn.split(':')[:5]
            if service in ('iam', 's3'):
                assert region == '', arn
            else:
                assert region == REGION, arn
            # Account: this one, AWS-owned ('aws'), or deliberately none/any where AWS has no owner.
            assert account in (ACCOUNT, 'aws', '', '*'), arn
            if account in ('', '*'):
                # buckets, public AMIs, published layers, API Gateway (its ARNs never carry an account)
                assert service in ('s3', 'ec2', 'lambda', 'apigateway'), arn
    assert 'secret-access-key' not in io.open(os.path.join(BUNDLE_DIR, 'README.md')).read().lower()
    assert not re.search(r'\b(AKIA|ASIA)[A-Z0-9]{16}\b', io.open(os.path.join(BUNDLE_DIR, 'README.md')).read())


def test_bundle_fits_iam_and_identity_center_quotas():
    for entry, document in zip(MANAGED, _documents()[:-1]):
        assert bundle.policy_characters(document) == entry['characters'] <= 6144
    inline_text = io.open(os.path.join(BUNDLE_DIR, INLINE['file'])).read()
    assert bundle.policy_characters(_documents()[-1]) == INLINE['characters'] <= 10240
    assert len(inline_text.encode()) <= 32768
    assert len(MANAGED) <= 10


def test_every_action_and_condition_key_is_in_the_aws_catalogue():
    known_keys = set(REFERENCE['global_condition_keys'])
    for keys in REFERENCE['condition_keys'].values():
        known_keys |= set(keys)
    for statement in _statements():
        for action in statement.get('Action', []) + statement.get('NotAction', []):
            prefix, name = action.split(':', 1)
            catalogue = REFERENCE['iam_actions'][prefix]
            assert not catalogue or name.endswith('*') or name in catalogue, action
        for tests in statement.get('Condition', {}).values():
            for key in tests:
                assert key in known_keys or key.split('/')[0] + '/${TagKey}' in known_keys, key


@pytest.mark.parametrize('action', ['iam:CreatePolicyVersion', 'iam:DeletePolicy', 'iam:SetDefaultPolicyVersion',
                                    'iam:DeletePolicyVersion', 'iam:TagPolicy'])
def test_holders_cannot_change_the_bundle_policies(action):
    for entry in MANAGED:
        assert _decide(action, f'arn:aws:iam::{ACCOUNT}:policy/{entry["name"]}',
                       statements=_statements()) == 'deny', entry['name']


@pytest.mark.parametrize('action, resource, context, expected', [
    ('cloudformation:CreateChangeSet', f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/c4-datastore-x/1', {},
     'allow'),
    ('cloudformation:CreateChangeSet', f'arn:aws:cloudformation:{REGION}:210987654321:stack/c4-datastore-x/1', {},
     'implicit-deny'),
    ('cloudformation:CreateChangeSet', f'arn:aws:cloudformation:us-west-2:{ACCOUNT}:stack/c4-datastore-x/1',
     {'aws:RequestedRegion': 'us-west-2'}, 'deny'),
    ('cloudformation:DeleteStack', f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/StackSet-baseline/1', {},
     'deny'),
    ('iam:PassRole', f'arn:aws:iam::{ACCOUNT}:role/c4-iam-main-stack-SMaHTECSRole-X',
     {'iam:PassedToService': 'ecs-tasks.amazonaws.com'}, 'allow'),
    ('iam:PutRolePolicy', f'arn:aws:iam::{ACCOUNT}:role/aws-reserved/sso.amazonaws.com/'
                          'AWSReservedSSO_SMaHT-Deployment-Manager_0123456789abcdef', {}, 'implicit-deny'),
    ('s3:PutObject', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': ACCOUNT}, 'allow'),
    ('s3:DeleteObject', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': ACCOUNT}, 'deny'),
    ('kms:ScheduleKeyDeletion', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/k', {}, 'deny'),
    ('ssm:StartSession', '*', {}, 'deny'),
    # Tibanna: deployment in this account and Region; never its execution.
    ('iam:CreatePolicy', f'arn:aws:iam::{ACCOUNT}:policy/tibanna_tiger_smaht-production_bucket_access', {},
     'allow'),
    ('iam:CreatePolicy', f'arn:aws:iam::{ACCOUNT}:policy/Anything', {}, 'deny'),
    ('iam:CreateGroup', f'arn:aws:iam::{ACCOUNT}:group/tibanna_tiger_smaht-production', {}, 'allow'),
    ('iam:AttachGroupPolicy', f'arn:aws:iam::{ACCOUNT}:group/tibanna_tiger_smaht-production',
     {'iam:PolicyARN': 'arn:aws:iam::aws:policy/AdministratorAccess'}, 'deny'),
    ('iam:AttachRolePolicy', f'arn:aws:iam::{ACCOUNT}:role/tibanna_tiger_smaht-production_run_task',
     {'iam:PolicyARN': 'arn:aws:iam::aws:policy/AmazonEC2FullAccess'}, 'allow'),
    ('iam:PassRole', f'arn:aws:iam::{ACCOUNT}:role/tibanna_tiger_smaht-production_run_task',
     {'iam:PassedToService': 'lambda.amazonaws.com',
      'iam:AssociatedResourceArn': f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:run_task_tiger_smaht-production'},
     'allow'),
    ('iam:PassRole', f'arn:aws:iam::210987654321:role/tibanna_tiger_smaht-production_states',
     {'iam:PassedToService': 'states.amazonaws.com'}, 'implicit-deny'),
    ('states:CreateStateMachine', f'arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:tibanna_tiger_smaht-production',
     {}, 'allow'),
    ('states:StartExecution', f'arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:tibanna_tiger_smaht-production',
     {}, 'deny'),
    ('lambda:InvokeFunction', f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:run_task_tiger_smaht-production', {},
     'deny'),
    ('ec2:RunInstances', f'arn:aws:ec2:{REGION}:{ACCOUNT}:instance/*',
     {'ec2:InstanceProfile': f'arn:aws:iam::{ACCOUNT}:instance-profile/tibanna_tiger_smaht-production_for_ec2'},
     'deny'),
    ('dynamodb:CreateTable', f'arn:aws:dynamodb:{REGION}:{ACCOUNT}:table/tibanna-master', {}, 'allow'),
])
def test_bundle_permissions_for_this_account(action, resource, context, expected):
    assert _decide(action, resource, dict({'aws:RequestedRegion': REGION}, **context),
                   statements=_statements()) == expected


def test_check_reports_a_stale_bundle(tmp_path, capsys):
    stale = tmp_path / 'bundle'
    shutil.copytree(BUNDLE_DIR, stale)
    path = stale / MANAGED[0]['file']
    path.write_text(path.read_text().replace('cloudformation:ListStacks', 'cloudformation:ListStack'))
    args = ARGS[:-1] + [str(stale)]
    assert bundle.main(args + ['--check']) == bundle.EXIT_ERROR
    out = capsys.readouterr().out
    assert f'{MANAGED[0]["file"]},differs' in out and 'help:' in out


@pytest.mark.parametrize('bad', [['--account-id', '5177'], ['--region', 'useast1'], ['--policy-prefix', 'a b']])
def test_invalid_arguments_are_usage_errors(bad, capsys):
    args = list(ARGS)
    args[args.index(bad[0]) + 1] = bad[1]
    with pytest.raises(SystemExit) as exit_:
        bundle.main(args)
    assert exit_.value.code == bundle.EXIT_USAGE
    assert capsys.readouterr().out.startswith('error:')


def test_materialize_refuses_other_intrinsics():
    with pytest.raises(bundle.UnresolvedValue):
        bundle.materialize({'Fn::ImportValue': 'x'}, ACCOUNT, REGION)
    with pytest.raises(bundle.UnresolvedValue):
        bundle.materialize({'Ref': 'SomeParameter'}, ACCOUNT, REGION)


def test_setup_guide_names_every_component_and_the_exact_target():
    guide = io.open(os.path.join(BUNDLE_DIR, 'README.md')).read()
    for needle in [ACCOUNT, REGION, '`SMaHT-Deployment-Manager`', INLINE['file'], 'path `/`', 'deploying_iam_user',
                   'provision-permission-set', '--target-id 517723527581', 'ReadOnlyAccess', 'AmazonS3FullAccess',
                   'AmazonSSMFullAccess', 'AmazonSageMakerFullAccess', 'AWSSupportAccess', 'Step 0',
                   'arn:aws:iam::517723527581:role/aws-reserved/sso.amazonaws.com/'
                   'AWSReservedSSO_SMaHT-Deployment-Manager_']:
        assert needle in guide, needle
    for entry in MANAGED:
        assert f'--policy-name {entry["name"]}' in guide and entry['description'] in guide
    # Commands name the Region explicitly instead of relying on a local profile default.
    commands = re.findall(r'\baws (?:iam|sso-admin|sts) [a-z-]+[^`\n]*', guide)
    assert commands and all('--region us-east-1' in command for command in commands), commands
