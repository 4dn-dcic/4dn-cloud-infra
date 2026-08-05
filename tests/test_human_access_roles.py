"""
Static/template tests for the opt-in human direct-AWS-access roles built by C4IAM.

These roles exist so a developer can inspect the running system, and a power user can perform the
reversible operational actions needed to remediate it, without assuming the existing DevRole
(which is trusted by the account root and holds ten full-access managed policies).

The scoping model these tests pin: the account holds only our own resources, so the policies do
*not* enumerate resource identifiers. Where an action supports resource-level authorization it is
scoped to the service (`arn:aws:ecs:<region>:<account>:service/*`, `arn:aws:s3:::*/*`, ...); where
an action has no resource-level authorization at all, the resource is `"*"` and the statement is
region-pinned instead. The constraint that carries the weight is therefore the *action list*, which
is fully enumerated - so these tests check that list closely.

Covered here, in the order the requirements were stated:

  1. Disabled-default behaviour - no resources, outputs, parameters or conditions added.
  2. Trust restrictions - enumerated principal ARNs, attributable session, never account root.
  3. Service-level resource scope - and `"*"` only in the two statements whose actions AWS gives
     no ARN to scope to.
  4. Constrained allowed actions - every action enumerated, no `service:*` and no `"*"`.
  5. Prohibited broad administration - no managed policies, and the administrative/destructive
     actions are explicitly denied.
  6. The README's illustrative JSON matches what the template actually renders.
"""
import io
import json
import os
import re
from unittest import mock

import pytest

from src.c4name import C4Name
from src.constants import Settings
from src.part import C4Tags, C4Account
from src.parts import iam as iam_mod
from src.parts.iam import C4IAM
from troposphere import Template


TEST_ENV_NAME = 'cgap-build'
TEST_ACCOUNT = '123456789'
ALICE = 'arn:aws:iam::123456789:user/alice'
BOB = 'arn:aws:iam::123456789:user/bob'
SSO_PRINCIPAL = ('arn:aws:iam::123456789:role/aws-reserved/sso.amazonaws.com/'
                 'AWSReservedSSO_Developer_abc123')

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
README = os.path.join(REPO_ROOT, 'README.md')

# The IAM stack as it stands before any of this is enabled.
PRE_EXISTING_RESOURCES = {
    'C4IAMMainApplicationS3Federator',
    'CGAPDevRole',
    'CGAPECSAutoscalingRole',
    'CGAPECSInstanceProfile',
    'CGAPECSRole',
    'VPCFlowLogRole',
}
PRE_EXISTING_OUTPUTS = {
    'C4IAMMainECSAssumedIAMRole',
    'C4IAMMainECSAutoscalingIAMRole',
    'C4IAMMainECSDevUserRole',
    'C4IAMMainECSInstanceProfile',
    'C4IAMMainECSS3IAMUser',
}
BOUNDARY_ID = 'C4IAMMainHumanAccessBoundary'

BASE_CONFIG = {
    Settings.APP_KIND: 'cgap',
    Settings.ENV_NAME: TEST_ENV_NAME,
    Settings.ACCOUNT_NUMBER: TEST_ACCOUNT,
}
_MISSING = object()

ENABLED_BOTH = {
    Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: True,
    Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: f'{ALICE}, {BOB}',
    Settings.HUMAN_ACCESS_REMEDIATE_ENABLED: True,
    Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS: ALICE,
}
BOTH_ROLES = (C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE)


def _make_iam_part() -> C4IAM:
    name = C4Name('c4-iam-main', title_token='C4IAMMain')
    return C4IAM(name=name, tags=C4Tags(),
                 account=C4Account(account_number=TEST_ACCOUNT, creds_file='/dev/null'))


def _build_template(**overrides) -> dict:
    """ Builds the IAM template with the given human_access.* settings in effect.

        Note the per-setting side_effect: a single return_value would make every config lookup
        answer the same thing, and these tests turn on some settings while leaving others off.
    """
    config = dict(BASE_CONFIG)
    config.update(overrides)

    def fake_get_config_setting(var, default=_MISSING, **kwargs):
        if var in config:
            return config[var]
        if default is _MISSING:
            raise KeyError(var)
        return default

    with mock.patch.object(iam_mod.ConfigManager, 'get_config_setting',
                           side_effect=fake_get_config_setting):
        return _make_iam_part().build_template(Template()).to_dict()


def _role(template: dict, logical_id: str) -> dict:
    assert logical_id in template['Resources'], f'{logical_id} was not built'
    return template['Resources'][logical_id]['Properties']


def _statements(role_properties: dict) -> list:
    return [statement
            for policy in role_properties.get('Policies', [])
            for statement in policy['PolicyDocument']['Statement']]


def _as_list(value) -> list:
    return value if isinstance(value, list) else [value]


def _actions(statement: dict) -> list:
    return _as_list(statement.get('Action', statement.get('NotAction', [])))


def _resources(statement: dict) -> list:
    return _as_list(statement.get('Resource', statement.get('NotResource', [])))


def _allows(role_properties: dict) -> list:
    return [s for s in _statements(role_properties) if s['Effect'] == 'Allow']


def _statements_allowing(role_properties: dict, action: str) -> list:
    return [s for s in _allows(role_properties) if action in _actions(s)]


def _denied_actions(role_properties: dict) -> set:
    return {action
            for statement in _statements(role_properties)
            if statement['Effect'] == 'Deny'
            for action in _actions(statement)}


def _render(value) -> str:
    """ Renders a resource entry - possibly an Fn::Join over CloudFormation pseudo-parameters -
        into a comparable string, so a service-level ARN can be asserted on directly.
    """
    if isinstance(value, dict):
        if 'Fn::Join' in value:
            separator, parts = value['Fn::Join']
            return separator.join(_render(part) for part in parts)
        if value == {'Ref': 'AWS::Region'}:
            return '<region>'
        if value == {'Ref': 'AWS::AccountId'}:
            return '<account-id>'
    return str(value)


def _flat(value) -> str:
    return json.dumps(value, sort_keys=True)


def _action_map(role_properties: dict) -> dict:
    """ {Sid: sorted(actions)} across all of a role's inline policies. This is the shape compared
        against the README, and it stays stable under resource/condition changes.
    """
    result = {}
    for statement in _statements(role_properties):
        sid = statement['Sid']
        assert sid not in result, f'duplicate Sid {sid!r}'
        result[sid] = sorted(_actions(statement))
    return result


# ---------------------------------------------------------------------------------------------
# 1. Disabled-default behaviour
# ---------------------------------------------------------------------------------------------

def test_human_access_roles_are_absent_by_default():
    """ The whole point of the opt-in: with no configuration, nothing is added. """
    template = _build_template()
    assert set(template['Resources']) == PRE_EXISTING_RESOURCES
    assert set(template['Outputs']) == PRE_EXISTING_OUTPUTS
    # No CloudFormation Parameters or Conditions were introduced either, so applying this to an
    # existing stack cannot prompt for a new parameter value.
    assert 'Parameters' not in template
    assert 'Conditions' not in template
    rendered = _flat(template)
    for token in ('HumanAccess', 'Diagnose', 'Remediate', 'human_access'):
        assert token not in rendered, f'{token!r} leaked into the default template'


def test_default_template_still_contains_the_untouched_dev_role():
    """ This work adds roles; it does not change or retire the existing DevRole. """
    dev_role = _role(_build_template(), 'CGAPDevRole')
    assert len(dev_role['ManagedPolicyArns']) == 10
    assert dev_role['AssumeRolePolicyDocument']['Statement'][0]['Principal'] == {
        'AWS': {'Ref': 'AWS::AccountId'}}


@pytest.mark.parametrize('enabled_setting, principals_setting, logical_id', [
    (Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED, Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS,
     C4IAM.DIAGNOSE_ROLE),
    (Settings.HUMAN_ACCESS_REMEDIATE_ENABLED, Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS,
     C4IAM.REMEDIATE_ROLE),
])
def test_enabling_without_approved_principals_creates_nothing(enabled_setting, principals_setting,
                                                              logical_id):
    """ Fails closed rather than falling back to account-root trust. """
    template = _build_template(**{enabled_setting: True})
    assert logical_id not in template['Resources']
    assert set(template['Resources']) == PRE_EXISTING_RESOURCES

    # ... and an empty string is treated the same as absent.
    template = _build_template(**{enabled_setting: True, principals_setting: '  ,  '})
    assert logical_id not in template['Resources']


def test_each_role_can_be_enabled_independently():
    template = _build_template(**{Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: True,
                                  Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: ALICE})
    assert C4IAM.DIAGNOSE_ROLE in template['Resources']
    assert C4IAM.REMEDIATE_ROLE not in template['Resources']

    template = _build_template(**{Settings.HUMAN_ACCESS_REMEDIATE_ENABLED: True,
                                  Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS: ALICE})
    assert C4IAM.REMEDIATE_ROLE in template['Resources']
    assert C4IAM.DIAGNOSE_ROLE not in template['Resources']


def test_enabled_template_adds_only_the_expected_resources():
    template = _build_template(**ENABLED_BOTH)
    assert set(template['Resources']) - PRE_EXISTING_RESOURCES == {
        C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE, BOUNDARY_ID}
    added_outputs = set(template['Outputs']) - PRE_EXISTING_OUTPUTS
    assert added_outputs == {f'C4IAMMain{C4IAM.DIAGNOSE_ROLE}Name',
                             f'C4IAMMain{C4IAM.REMEDIATE_ROLE}Name'}
    # The opt-in outputs are not exported: no other stack should depend on this feature.
    for output in added_outputs:
        assert 'Export' not in template['Outputs'][output]


# ---------------------------------------------------------------------------------------------
# 2. Trust restrictions
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_trust_policy_never_trusts_the_account_root(logical_id):
    trust = _flat(_role(_build_template(**ENABLED_BOTH), logical_id)['AssumeRolePolicyDocument'])
    assert 'AWS::AccountId' not in trust
    assert ':root' not in trust


def test_trust_policy_pins_exactly_the_supplied_principals():
    template = _build_template(**ENABLED_BOTH)
    allow = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']['Statement'][0]
    assert allow['Effect'] == 'Allow'
    assert allow['Principal'] == {'AWS': [ALICE, BOB]}
    assert '*' not in allow['Principal']['AWS']

    # The remediation role has its own, smaller principal list.
    remediate_trust = _role(template, C4IAM.REMEDIATE_ROLE)['AssumeRolePolicyDocument']
    assert remediate_trust['Statement'][0]['Principal'] == {'AWS': [ALICE]}


def test_trust_policy_requires_an_attributable_mfa_session():
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_SOURCE_IDENTITY_PATTERN: '*@hms.harvard.edu'}))
    trust = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']
    allow_condition = trust['Statement'][0]['Condition']
    assert allow_condition['Bool'] == {'aws:MultiFactorAuthPresent': 'true'}
    assert allow_condition['NumericLessThan'] == {'aws:MultiFactorAuthAge': '3600'}
    assert allow_condition['StringLike'] == {'sts:SourceIdentity': '*@hms.harvard.edu'}

    # A session with no SourceIdentity is refused outright, so CloudTrail always names a person.
    deny = trust['Statement'][1]
    assert deny['Effect'] == 'Deny'
    assert deny['Condition'] == {'Null': {'sts:SourceIdentity': 'true'}}

    # There is no sts:DurationSeconds condition key; MaxSessionDuration is the real control.
    assert 'DurationSeconds' not in _flat(trust)


def test_session_duration_is_bounded_and_shorter_for_remediation():
    template = _build_template(**ENABLED_BOTH)
    diagnose = _role(template, C4IAM.DIAGNOSE_ROLE)
    remediate = _role(template, C4IAM.REMEDIATE_ROLE)
    assert diagnose['MaxSessionDuration'] == 3600
    assert remediate['MaxSessionDuration'] == 1800
    assert remediate['MaxSessionDuration'] < diagnose['MaxSessionDuration']


def test_mfa_condition_can_be_dropped_for_sso_accounts_without_losing_attribution():
    """ In an Identity Center account aws:MultiFactorAuthPresent is asserted upstream and cannot be
        relied on; the principal pin and SourceIdentity requirement still stand.
    """
    template = _build_template(**{
        Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: True,
        Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: SSO_PRINCIPAL,
        Settings.HUMAN_ACCESS_REQUIRE_MFA: False,
    })
    trust = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']
    assert 'MultiFactorAuthPresent' not in _flat(trust)
    assert trust['Statement'][0]['Principal'] == {'AWS': [SSO_PRINCIPAL]}
    assert trust['Statement'][1]['Condition'] == {'Null': {'sts:SourceIdentity': 'true'}}
    assert 'AWS::AccountId' not in _flat(trust)


# ---------------------------------------------------------------------------------------------
# 3. Service-level resource scope
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_wildcard_resources_appear_only_in_the_unscopable_read_statements(logical_id):
    """ A bare "*" resource is permitted only where AWS offers no resource-level authorization for
        the actions involved. Those statements are named, read-only and region-pinned.
    """
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    for statement in _allows(role):
        if '*' in _resources(statement):
            assert statement['Sid'] in C4IAM.UNSCOPABLE_READ_SIDS, (
                f"{logical_id} statement {statement['Sid']!r} uses Resource '*' but is not one of"
                f" the declared unscopable read statements")
            assert statement['Condition'] == {
                'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_every_other_allow_is_scoped_to_a_service_level_arn(logical_id):
    """ Service-level, not identifier-level: an ARN naming the service (and normally this account
        and region), with a trailing wildcard standing in for "every resource of this type".
    """
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    scoped = [s for s in _allows(role) if s['Sid'] not in C4IAM.UNSCOPABLE_READ_SIDS]
    assert scoped, f'{logical_id} has no resource-scoped statements'
    for statement in scoped:
        for resource in _resources(statement):
            rendered = _render(resource)
            assert rendered.startswith('arn:aws:'), rendered
            assert '*' in rendered, f'{rendered} is not service-level scoped'
            # S3 ARNs carry neither region nor account; everything else must carry both.
            if not rendered.startswith('arn:aws:s3:::'):
                assert '<account-id>' in rendered, rendered


def test_diagnostic_resource_scopes_are_service_level_for_each_supported_service():
    """ Pins the actual scope of each read that AWS lets us attach an ARN to. """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    expected = {
        'ReadApplicationLogs': ['arn:aws:logs:<region>:<account-id>:log-group:*',
                                'arn:aws:logs:<region>:<account-id>:log-group:*:log-stream:*'],
        'InspectBucketConfiguration': ['arn:aws:s3:::*'],
        'ReadObjects': ['arn:aws:s3:::*/*'],
        'ReadSecrets': ['arn:aws:secretsmanager:<region>:<account-id>:secret:*'],
        'InspectQueueDepth': ['arn:aws:sqs:<region>:<account-id>:*'],
        'InspectContainerImages': ['arn:aws:ecr:<region>:<account-id>:repository/*'],
        'InspectBuildsAndWorkflows': ['arn:aws:codebuild:<region>:<account-id>:project/*'],
        'InspectWorkflowExecutions': ['arn:aws:states:<region>:<account-id>:*'],
        'InspectKeyMetadata': ['arn:aws:kms:<region>:<account-id>:key/*'],
        'InspectOwnRoleDefinition': ['arn:aws:iam::<account-id>:role/*'],
    }
    actual = {s['Sid']: [_render(r) for r in _resources(s)]
              for s in _allows(diagnose) if s['Sid'] in expected}
    assert actual == expected


def test_remediation_resource_scopes_are_service_level_for_each_action():
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    expected = {
        'RestartOrRescaleServices': ['arn:aws:ecs:<region>:<account-id>:service/*'],
        'StopStuckTasks': ['arn:aws:ecs:<region>:<account-id>:task/*'],
        'ReleaseInFlightQueueMessages': ['arn:aws:sqs:<region>:<account-id>:*'],
        'StartWorkflowExecutions': ['arn:aws:states:<region>:<account-id>:stateMachine:*'],
        'StopWorkflowExecutions': ['arn:aws:states:<region>:<account-id>:execution:*'],
        'RebuildApplicationImageViaCiOnly': ['arn:aws:codebuild:<region>:<account-id>:project/*'],
    }
    actual = {s['Sid']: [_render(r) for r in _resources(s)]
              for s in _allows(remediate) if s['Sid'] in expected}
    assert actual == expected


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_no_resource_identifiers_are_baked_into_the_policies(logical_id):
    """ Service-level scope means no env name, bucket name or queue name should appear at all. """
    rendered = _flat(_role(_build_template(**ENABLED_BOTH), logical_id)['Policies'])
    for token in (TEST_ENV_NAME, 'C4AppConfig', 'C4Datastore', 'application-files',
                  'foursight', 'c4-logging'):
        assert token not in rendered, f'{token!r} is a resource identifier and should not appear'


# ---------------------------------------------------------------------------------------------
# 4. Constrained allowed actions
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_no_role_ever_grants_action_star_or_a_service_wide_wildcard(logical_id):
    """ The action list is the real constraint, so it must be fully enumerated. """
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    for statement in _allows(role):
        for action in _actions(statement):
            assert action != '*', f"{logical_id} grants Action '*'"
            assert not re.fullmatch(r'[a-z0-9-]+:\*', action), (
                f'{logical_id} grants the service-wide wildcard {action!r}')
    rendered = _flat(role['Policies'])
    for blanket in ('"ecs:*"', '"es:*"', '"sqs:*"', '"s3:*"', '"elasticloadbalancing:*"'):
        assert blanket not in rendered, f'{logical_id} grants {blanket}'


DIAGNOSTIC_READS = [
    'ecs:DescribeServices',          # is the portal up
    'ecs:DescribeTasks',             # why did a task die
    'elasticloadbalancing:DescribeTargetHealth',
    'cloudwatch:GetMetricData',      # is RDS saturated, is OpenSearch red
    'logs:FilterLogEvents',          # what is the stack trace
    'logs:StartQuery',
    'rds:DescribeDBInstances',
    'sqs:GetQueueAttributes',        # is indexing backed up (depth, not bodies)
    'cloudformation:DescribeStackEvents',
    'ecr:DescribeImages',            # which image is actually running
    'es:DescribeDomain',
    'secretsmanager:GetSecretValue',  # retained, resource-scoped, per captain decision
    's3:GetObject',
]


@pytest.mark.parametrize('action', DIAGNOSTIC_READS)
def test_diagnostic_role_allows_the_distinct_reads_the_services_require(action):
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    assert _statements_allowing(diagnose, action), f'{action} is not allowed'
    assert action not in _denied_actions(diagnose), f'{action} is both allowed and denied'


REMEDIATION_ACTIONS = {
    'ecs:UpdateService',            # restart / rescale
    'ecs:StopTask',                 # kill one stuck task
    'sqs:ChangeMessageVisibility',  # release in-flight messages
    'states:StartExecution',        # rerun a stuck workflow
    'states:StopExecution',
    'codebuild:StartBuild',         # rebuild through CI
    'codebuild:StopBuild',
    'codebuild:RetryBuild',
}


def test_remediation_grants_exactly_the_intended_operational_actions():
    """ The mutating surface is small and closed - nothing creeps in unnoticed. """
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    mutating = {action
                for statement in _allows(remediate)
                if statement['Sid'] not in C4IAM.UNSCOPABLE_READ_SIDS
                for action in _actions(statement)}
    assert mutating == REMEDIATION_ACTIONS


@pytest.mark.parametrize('action', sorted(REMEDIATION_ACTIONS))
def test_every_remediation_action_is_region_pinned_and_mfa_gated(action):
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    allowing = _statements_allowing(remediate, action)
    assert len(allowing) == 1
    condition = allowing[0]['Condition']
    assert condition['Bool'] == {'aws:MultiFactorAuthPresent': 'true'}
    assert condition['StringEquals'] == {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}


def test_irreversible_and_destructive_operations_are_excluded_from_remediation():
    """ SQS purge is excluded outright - not an opt-in - and denied so it stays excluded. """
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    denied = _denied_actions(remediate)
    for action in ('sqs:PurgeQueue', 'sqs:DeleteQueue', 'sqs:DeleteMessage', 's3:DeleteObject',
                   'ecs:DeleteService', 'ecs:DeleteCluster'):
        assert not _statements_allowing(remediate, action), f'{action} must not be granted'
        assert action in denied, f'{action} is not explicitly denied'
    # The reversible alternative is what remediation gets instead.
    assert _statements_allowing(remediate, 'sqs:ChangeMessageVisibility')


def test_remediation_reads_are_narrower_than_diagnostic_reads():
    """ Keeps CloudTrail separable into "someone was looking" and "someone was changing". """
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    for action in ('secretsmanager:GetSecretValue', 's3:GetObject', 'kms:Decrypt'):
        assert not _statements_allowing(remediate, action)
        assert action in _denied_actions(remediate)


def test_diagnostic_role_is_read_only():
    """ Every write the remediation role may do is denied here, so they are not interchangeable. """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    denied = _denied_actions(diagnose)
    for action in sorted(REMEDIATION_ACTIONS):
        assert action in denied, f'{action} is not denied to the read-only role'
    for action in ('s3:PutObject', 's3:DeleteObject', 'secretsmanager:PutSecretValue',
                   'cloudwatch:PutMetricAlarm', 'sqs:PurgeQueue'):
        assert action in denied, f'{action} is not denied to the read-only role'
    # Data-plane and configuration exfiltration paths a read-only role must not have.
    for action in ('sqs:ReceiveMessage', 'rds:DownloadCompleteDBLogFile',
                   'lambda:GetFunctionConfiguration', 'ssm:GetParameter'):
        assert action in denied, f'{action} is not denied to the read-only role'


def test_kms_decrypt_is_off_by_default_and_opt_in_only():
    """ At service scope Decrypt reaches every key in the account, so it keeps its own switch. """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    assert not _statements_allowing(diagnose, 'kms:Decrypt')
    assert not _statements_allowing(diagnose, 'kms:GetKeyPolicy')
    assert 'kms:Decrypt' in _denied_actions(diagnose)
    # Metadata stays available so bucket encryption is still diagnosable.
    assert _statements_allowing(diagnose, 'kms:DescribeKey')

    diagnose = _role(_build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True})), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, 'kms:Decrypt')
    assert len(allowing) == 1
    assert _render(_resources(allowing[0])[0]) == 'arn:aws:kms:<region>:<account-id>:key/*'
    assert 'kms:Decrypt' not in _denied_actions(diagnose)


# ---------------------------------------------------------------------------------------------
# 5. Prohibited broad administration
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_neither_role_attaches_any_managed_policy(logical_id):
    """ The ten managed policies on DevRole are what make it a superset of the runtime role. """
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    assert 'ManagedPolicyArns' not in role
    assert 'arn:aws:iam::aws:policy/' not in _flat(role)


FORBIDDEN_ACTIONS = [
    'ecr:PutImage',                 # authoring image content is CI's job, not a human's
    'ecr:InitiateLayerUpload',
    'ecs:RegisterTaskDefinition',   # no new task definitions
    'ecs:RunTask',
    'ecs:ExecuteCommand',           # no shell inside a running container
    'lambda:UpdateFunctionCode',
    'iam:PassRole',
    'sts:GetFederationToken',       # the S3 federator's escape hatch
    'sts:AssumeRole',               # no chaining into another role
]


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
@pytest.mark.parametrize('action', FORBIDDEN_ACTIONS)
def test_broad_privilege_is_explicitly_denied_on_both_roles(logical_id, action):
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    assert action in _denied_actions(role), f'{action} is not denied on {logical_id}'
    assert not _statements_allowing(role, action)


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_both_roles_carry_the_permission_boundary(logical_id):
    template = _build_template(**ENABLED_BOTH)
    assert template['Resources'][BOUNDARY_ID]['Type'] == 'AWS::IAM::ManagedPolicy'
    assert _role(template, logical_id)['PermissionsBoundary'] == {'Ref': BOUNDARY_ID}


def test_boundary_is_a_ceiling_not_an_administrative_grant():
    """ A boundary with no Allow grants nothing and makes both roles unusable, so the single
        Allow *:* is structural. The roles themselves never grant Action '*' (asserted above).
    """
    boundary = _build_template(**ENABLED_BOTH)['Resources'][BOUNDARY_ID]['Properties']
    document = boundary['PolicyDocument']
    allows = [s for s in document['Statement'] if s['Effect'] == 'Allow']
    assert len(allows) == 1
    assert allows[0]['Sid'] == 'CeilingOnly'
    assert allows[0]['Action'] == '*'
    assert 'ceiling' in boundary['Description'].lower()


def test_boundary_forbids_identity_infrastructure_and_destructive_operations():
    document = _build_template(**ENABLED_BOTH)['Resources'][BOUNDARY_ID]['Properties'][
        'PolicyDocument']
    denied = {action for s in document['Statement'] if s['Effect'] == 'Deny'
              for action in _actions(s)}
    for action in ('iam:Create*', 'iam:Attach*', 'iam:PassRole', 'sso-admin:*', 'organizations:*',
                   'cloudformation:UpdateStack', 'cloudformation:ExecuteChangeSet',
                   'ecr:PutImage', 'lambda:UpdateFunctionCode', 'ec2:AuthorizeSecurityGroup*',
                   'sqs:PurgeQueue', 'sqs:DeleteQueue', 'rds:Delete*', 's3:PutObject*'):
        assert action in denied, f'boundary does not forbid {action}'


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_every_role_denies_activity_outside_the_deployment_region(logical_id):
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    region_denies = [s for s in _statements(role)
                     if s['Effect'] == 'Deny' and 'NotAction' in s]
    assert len(region_denies) == 1
    assert region_denies[0]['Condition'] == {
        'StringNotEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}


def test_human_roles_do_not_reuse_the_ecs_runtime_role_policies():
    """ dev_user_role() shares four inline policy objects with the ECS runtime role, which is what
        makes human access a superset of runtime privilege. These roles must not repeat that.
    """
    template = _build_template(**ENABLED_BOTH)
    ecs_policy_names = {p['PolicyName'] for p in _role(template, 'CGAPECSRole')['Policies']}
    for logical_id in BOTH_ROLES:
        human_policy_names = {p['PolicyName'] for p in _role(template, logical_id)['Policies']}
        assert not (human_policy_names & ecs_policy_names)


def test_policies_fit_within_aws_iam_size_limits():
    """ Guards against a future addition silently breaking the deploy: AWS caps a role's inline
        policies at 10240 characters in total, and a managed policy document at 6144.
    """
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True}))
    for logical_id in BOTH_ROLES:
        size = sum(len(json.dumps(p['PolicyDocument'], separators=(',', ':')))
                   for p in _role(template, logical_id)['Policies'])
        assert size <= 10240, f'{logical_id} inline policies are {size} characters'
    boundary = template['Resources'][BOUNDARY_ID]['Properties']['PolicyDocument']
    boundary_size = len(json.dumps(boundary, separators=(',', ':')))
    assert boundary_size <= 6144, f'boundary policy is {boundary_size} characters'


# ---------------------------------------------------------------------------------------------
# 6. The README's illustrative policy examples
# ---------------------------------------------------------------------------------------------

README_HEADINGS = {
    C4IAM.DIAGNOSE_ROLE: '### Illustrative policy: diagnostic role',
    C4IAM.REMEDIATE_ROLE: '### Illustrative policy: remediation role',
}


def _readme_policy(logical_id: str) -> dict:
    """ Extracts the JSON policy document from the fenced block following a role's heading.

        Anchored on the heading rather than on block position, so adding an unrelated snippet
        elsewhere in the README cannot silently retarget this.
    """
    text = io.open(README).read()
    heading = README_HEADINGS[logical_id]
    assert heading in text, f'README is missing the heading {heading!r}'
    after_heading = text.split(heading, 1)[1]
    match = re.search(r'```json\n(.*?)\n```', after_heading, re.DOTALL)
    assert match, f'no fenced json block follows {heading!r}'
    return json.loads(match.group(1))


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_readme_policy_example_is_valid_and_well_formed(logical_id):
    document = _readme_policy(logical_id)
    assert document['Version'] == '2012-10-17'
    assert isinstance(document['Statement'], list) and document['Statement']
    for statement in document['Statement']:
        assert statement['Effect'] in ('Allow', 'Deny')
        assert 'Sid' in statement
        assert _actions(statement), f"{statement['Sid']} has no actions"


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_readme_policy_example_matches_what_the_template_renders(logical_id):
    """ Makes "aligned with the generated policy" a fact rather than a claim.

        Compared by {Sid: sorted(actions)}: resources are deliberately not compared, because the
        README uses <region>/<account-id> placeholders where the template emits Ref intrinsics.
    """
    generated = _action_map(_role(_build_template(**ENABLED_BOTH), logical_id))
    documented = {s['Sid']: sorted(_actions(s)) for s in _readme_policy(logical_id)['Statement']}
    assert documented == generated


@pytest.mark.parametrize('logical_id', BOTH_ROLES)
def test_readme_policy_example_is_not_presented_as_deployable(logical_id):
    """ The examples must not look copy-pasteable: placeholders, not real account values, and no
        CloudFormation intrinsics left in.
    """
    document = _readme_policy(logical_id)
    rendered = _flat(document)
    assert '"Ref"' not in rendered and 'Fn::Join' not in rendered
    assert '<account-id>' in rendered
    assert not re.search(r'\b\d{12}\b', rendered), 'a real-looking account id appears'
    # No Action '*' in the illustration either.
    for statement in document['Statement']:
        if statement['Effect'] == 'Allow':
            assert '*' not in _actions(statement)


def test_readme_labels_the_examples_non_authoritative_and_explains_the_scoping():
    text = io.open(README).read()
    section = text.split('## Human Direct AWS Access Roles', 1)[1].split('\n## ', 1)[0]
    # Explicitly non-authoritative, and points at the real source of truth.
    assert 'illustrative, not authoritative' in section
    assert 'src/parts/iam.py' in section
    assert 'not deployable as written' in section
    # Explains both halves of the scoping model, and the action constraint.
    assert 'service-level' in section.lower()
    assert 'aws:RequestedRegion' in section
    assert 'ceiling, not a grant' in section
