"""
Static/template tests for the opt-in human direct-AWS-access roles built by C4IAM.

These roles exist so a developer can inspect the running system, and a power user can perform a
small number of named, reversible operational writes, without assuming the existing DevRole
(which is trusted by the account root and holds ten full-access managed policies).

What is pinned here, in the order the requirements were stated:

  1. Disabled by default. With none of the human_access.* settings present, the IAM template is
     exactly what it was before - same resources, same outputs, no CloudFormation Parameters and
     no Conditions. A role is also not created when it is enabled but no approved principal ARNs
     were supplied, because the alternative (account-root trust) is the thing being fixed.
  2. Trust is restricted to enumerated principal ARNs with an attributable session, never to
     arn:aws:iam::<account>:root.
  3. The diagnostic role keeps resource-scoped Secrets Manager and S3 object reads, plus the
     observability reads needed to inspect services - and nothing on '*' that mutates.
  4. Broad privilege is denied: no managed policies at all, no supply-chain or identity writes,
     and every remediation write is on an explicitly supplied ARN.

Physical identifiers asserted here are derived the same way the rest of the repo derives them
(names.py for secrets, base.py bucket templates, C4Logging's stack name for log groups), so these
tests fail if that derivation drifts rather than encoding a second guess at the real names.
"""
import json
from unittest import mock

import pytest

from src.c4name import C4Name
from src.constants import Settings
from src.part import C4Tags, C4Account
from src.parts import iam as iam_mod
from src.parts.iam import C4IAM
from src.parts.logging import C4Logging
from troposphere import Template


TEST_ENV_NAME = 'cgap-build'
TEST_ACCOUNT = '123456789'
ALICE = 'arn:aws:iam::123456789:user/alice'
BOB = 'arn:aws:iam::123456789:user/bob'
SSO_PRINCIPAL = ('arn:aws:iam::123456789:role/aws-reserved/sso.amazonaws.com/'
                 'AWSReservedSSO_Developer_abc123')
TEST_KMS_KEY_ID = '27d040a3-ead1-4f5a-94ce-0fa6e7f84a95'

SERVICE_ARN = 'arn:aws:ecs:us-east-1:123456789:service/some-cluster/portal'
CLUSTER_ARN = 'arn:aws:ecs:us-east-1:123456789:cluster/some-cluster'
QUEUE_ARN = 'arn:aws:sqs:us-east-1:123456789:cgap-build-indexer'
STATE_MACHINE_ARN = 'arn:aws:states:us-east-1:123456789:stateMachine:tibanna_unicorn'
CODEBUILD_ARN = 'arn:aws:codebuild:us-east-1:123456789:project/main-build'

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

BASE_CONFIG = {
    Settings.APP_KIND: 'cgap',
    Settings.ENV_NAME: TEST_ENV_NAME,
    Settings.ACCOUNT_NUMBER: TEST_ACCOUNT,
}
_MISSING = object()

# Everything needed to actually get both roles built.
ENABLED_BOTH = {
    Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED: True,
    Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS: f'{ALICE}, {BOB}',
    Settings.HUMAN_ACCESS_REMEDIATE_ENABLED: True,
    Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS: ALICE,
}
REMEDIATION_TARGETS = {
    Settings.HUMAN_ACCESS_REMEDIATE_SERVICE_ARNS: SERVICE_ARN,
    Settings.HUMAN_ACCESS_REMEDIATE_CLUSTER_ARNS: CLUSTER_ARN,
    Settings.HUMAN_ACCESS_REMEDIATE_QUEUE_ARNS: QUEUE_ARN,
    Settings.HUMAN_ACCESS_REMEDIATE_STATE_MACHINE_ARNS: STATE_MACHINE_ARN,
    Settings.HUMAN_ACCESS_REMEDIATE_CODEBUILD_ARNS: CODEBUILD_ARN,
}


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


def _actions(statement: dict) -> list:
    actions = statement.get('Action', statement.get('NotAction', []))
    return actions if isinstance(actions, list) else [actions]


def _statements_allowing(role_properties: dict, action: str) -> list:
    return [s for s in _statements(role_properties)
            if s['Effect'] == 'Allow' and action in _actions(s)]


def _denied_actions(role_properties: dict) -> set:
    return {action
            for statement in _statements(role_properties)
            if statement['Effect'] == 'Deny'
            for action in _actions(statement)}


def _resources(statement: dict) -> list:
    resources = statement.get('Resource', statement.get('NotResource', []))
    return resources if isinstance(resources, list) else [resources]


def _flat(value) -> str:
    return json.dumps(value, sort_keys=True)


# ---------------------------------------------------------------------------------------------
# 1. Disabled by default
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


# ---------------------------------------------------------------------------------------------
# 2. Trust restrictions
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', [C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE])
def test_trust_policy_never_trusts_the_account_root(logical_id):
    template = _build_template(**ENABLED_BOTH)
    trust = _flat(_role(template, logical_id)['AssumeRolePolicyDocument'])
    assert 'AWS::AccountId' not in trust
    assert ':root' not in trust


def test_trust_policy_pins_exactly_the_supplied_principals():
    template = _build_template(**ENABLED_BOTH)
    diagnose_trust = _role(template, C4IAM.DIAGNOSE_ROLE)['AssumeRolePolicyDocument']
    allow = diagnose_trust['Statement'][0]
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
    # Not a back door to account-root trust.
    assert 'AWS::AccountId' not in _flat(trust)


# ---------------------------------------------------------------------------------------------
# 3. Approved diagnostic reads
# ---------------------------------------------------------------------------------------------

DIAGNOSTIC_READS = [
    'ecs:Describe*',                # is the portal up, why did a task die
    'ecs:List*',
    'elasticloadbalancing:Describe*',  # are target groups healthy
    'cloudwatch:Get*',              # is RDS saturated, is OpenSearch red
    'logs:Describe*',
    'rds:Describe*',
    'sqs:GetQueueAttributes',       # is indexing backed up (depth, not message bodies)
    'cloudformation:Describe*',     # did the last deploy succeed
    'ecr:Describe*',                # which image is actually running
    'es:Describe*',
    'ec2:Describe*',
]


@pytest.mark.parametrize('action', DIAGNOSTIC_READS)
def test_diagnostic_role_allows_the_approved_observability_reads(action):
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, action)
    assert allowing, f'{action} is not allowed to the diagnostic role'
    # These APIs have no resource-level authorization, so they are on '*' but region-pinned.
    for statement in allowing:
        assert statement['Condition'] == {'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}


def test_diagnostic_role_can_read_application_logs_scoped_to_this_deployment():
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, 'logs:FilterLogEvents')
    assert len(allowing) == 1
    resources = _resources(allowing[0])
    rendered = _flat(resources)
    # Log groups have no LogGroupName, so their physical names are CloudFormation-generated and
    # can only be matched by the logging stack's prefix. Derive it rather than restating it.
    assert f'{C4Logging.suggest_stack_name().stack_name}-*' in rendered
    assert f'/aws/rds/instance/rds-{TEST_ENV_NAME}/*' in rendered
    # Every ARN is a scoped Fn::Join, never a bare '*' matching every log group in the account.
    # (A '*' does appear inside them as the log-stream segment, which is expected.)
    assert resources and all(resource != '*' for resource in resources)


def test_diagnostic_secret_reads_are_retained_but_resource_scoped():
    """ Captain decision: developers keep direct Secrets Manager reads, scoped to the application's
        own secrets, so they can inspect the system and bring evidence.
    """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, 'secretsmanager:GetSecretValue')
    assert allowing, 'the diagnostic role must retain GetSecretValue'
    assert len(allowing) == 1
    resources = _flat(_resources(allowing[0]))
    # The real secret names, per names.py: the app configuration (GAC) and the RDS master secret.
    assert 'C4AppConfigCgapBuild' in resources
    assert 'C4DatastoreCgapBuildRDSSecret' in resources
    # Never the ECS role's unscoped grant.
    assert '"*"' not in resources
    assert 'GetSecretValue' not in _denied_actions(diagnose)


def test_diagnostic_object_reads_are_retained_but_scoped_to_application_buckets():
    """ Same decision for S3 objects: kept, but only in this deployment's own buckets. """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, 's3:GetObject')
    assert allowing, 'the diagnostic role must retain s3:GetObject'
    assert len(allowing) == 1
    resources = _resources(allowing[0])
    assert resources, 'no buckets were scoped'
    for resource in resources:
        assert resource.startswith(f'arn:aws:s3:::{TEST_ENV_NAME}-'), resource
        assert resource.endswith('/*'), resource
    # Derived from base.py's bucket templates, so the real application buckets are covered.
    assert f'arn:aws:s3:::{TEST_ENV_NAME}-application-files/*' in resources
    assert f'arn:aws:s3:::{TEST_ENV_NAME}-application-wfoutput/*' in resources
    assert 's3:GetObject' not in _denied_actions(diagnose)


def test_diagnostic_bucket_list_can_be_supplied_explicitly_for_legacy_names():
    """ Not every environment's buckets follow the derived pattern, so the list is overridable. """
    diagnose = _role(_build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_BUCKETS: 'foursight-prod-envs, legacy-application-files',
    })), C4IAM.DIAGNOSE_ROLE)
    resources = _resources(_statements_allowing(diagnose, 's3:GetObject')[0])
    assert resources == ['arn:aws:s3:::foursight-prod-envs/*',
                         'arn:aws:s3:::legacy-application-files/*']


def test_kms_decrypt_is_off_by_default_and_scoped_to_the_configured_key_when_enabled():
    with_key = dict(ENABLED_BOTH, **{Settings.S3_ENCRYPT_KEY_ID: TEST_KMS_KEY_ID})

    # Off by default: metadata only, and Decrypt is explicitly denied.
    diagnose = _role(_build_template(**with_key), C4IAM.DIAGNOSE_ROLE)
    assert not _statements_allowing(diagnose, 'kms:Decrypt')
    assert 'kms:Decrypt' in _denied_actions(diagnose)
    assert _statements_allowing(diagnose, 'kms:DescribeKey')
    # The more revealing key-policy read is scoped to the configured key.
    key_policy_reads = _statements_allowing(diagnose, 'kms:GetKeyPolicy')
    assert len(key_policy_reads) == 1
    assert f'key/{TEST_KMS_KEY_ID}' in _flat(_resources(key_policy_reads[0]))

    # Enabled: allowed on exactly the one configured key, never '*', and no longer denied.
    diagnose = _role(_build_template(**dict(
        with_key, **{Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True})), C4IAM.DIAGNOSE_ROLE)
    allowing = _statements_allowing(diagnose, 'kms:Decrypt')
    assert len(allowing) == 1
    resources = _flat(_resources(allowing[0]))
    assert f'key/{TEST_KMS_KEY_ID}' in resources
    assert '"*"' not in resources
    assert 'kms:Decrypt' not in _denied_actions(diagnose)


def test_no_key_material_access_without_a_configured_key_but_metadata_still_readable():
    """ Never a '*' fallback for Decrypt or for the key-policy read when s3.encrypt_key_id is
        unset - which is the common case, only smaht-wolf configures one. Plain key metadata stays
        available so "is this bucket encrypted, and with which key" remains answerable.
    """
    diagnose = _role(_build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True})), C4IAM.DIAGNOSE_ROLE)
    assert not _statements_allowing(diagnose, 'kms:Decrypt')
    assert not _statements_allowing(diagnose, 'kms:GetKeyPolicy')

    metadata_reads = _statements_allowing(diagnose, 'kms:DescribeKey')
    assert len(metadata_reads) == 1
    # Metadata only, and region-pinned: no key material, no ciphertext, no key policy.
    assert metadata_reads[0]['Condition'] == {
        'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}
    granted = set(_actions(metadata_reads[0]))
    assert not granted & {'kms:Decrypt', 'kms:GenerateDataKey', 'kms:ReEncryptFrom',
                          'kms:GetKeyPolicy', 'kms:CreateGrant'}


# ---------------------------------------------------------------------------------------------
# 4. Denied broad privilege
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('logical_id', [C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE])
def test_neither_role_attaches_any_managed_policy(logical_id):
    """ The ten managed policies on DevRole are what make it a superset of the runtime role. """
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    assert 'ManagedPolicyArns' not in role
    assert 'arn:aws:iam::aws:policy/' not in _flat(role)


@pytest.mark.parametrize('logical_id', [C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE])
def test_both_roles_carry_the_permission_boundary(logical_id):
    template = _build_template(**ENABLED_BOTH)
    role = _role(template, logical_id)
    boundary_id = 'C4IAMMainHumanAccessBoundary'
    assert template['Resources'][boundary_id]['Type'] == 'AWS::IAM::ManagedPolicy'
    assert role['PermissionsBoundary'] == {'Ref': boundary_id}


# Privileges neither human role may hold, each tied to why it matters.
FORBIDDEN_ACTIONS = [
    'ecr:PutImage',                 # authoring image content is CI's job, not a human's
    'ecr:InitiateLayerUpload',
    'ecs:RegisterTaskDefinition',   # no new task definitions
    'ecs:RunTask',
    'ecs:ExecuteCommand',           # no shell inside a running container
    'iam:PassRole',
    'sts:GetFederationToken',       # the S3 federator's escape hatch
    'sts:AssumeRole',               # no chaining into another role
]


@pytest.mark.parametrize('logical_id', [C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE])
@pytest.mark.parametrize('action', FORBIDDEN_ACTIONS)
def test_broad_privilege_is_explicitly_denied_on_both_roles(logical_id, action):
    role = _role(_build_template(**dict(ENABLED_BOTH, **REMEDIATION_TARGETS)), logical_id)
    assert action in _denied_actions(role), f'{action} is not denied on {logical_id}'
    assert not _statements_allowing(role, action)


def test_diagnostic_role_is_read_only():
    """ Every write the remediation role may do is denied here, so the two are not interchangeable.
    """
    diagnose = _role(_build_template(**ENABLED_BOTH), C4IAM.DIAGNOSE_ROLE)
    denied = _denied_actions(diagnose)
    for action in ('ecs:UpdateService', 'ecs:StopTask', 'sqs:PurgeQueue', 'codebuild:StartBuild',
                   'states:StartExecution', 's3:PutObject', 's3:DeleteObject',
                   'secretsmanager:PutSecretValue', 'cloudwatch:PutMetricAlarm'):
        assert action in denied, f'{action} is not denied to the read-only role'
    # Data-plane and configuration exfiltration paths that a read-only role must not have.
    for action in ('sqs:ReceiveMessage', 'rds:DownloadCompleteDBLogFile',
                   'lambda:GetFunctionConfiguration', 'ssm:GetParameter'):
        assert action in denied, f'{action} is not denied to the read-only role'


def test_no_mutating_action_is_ever_granted_on_a_wildcard_resource():
    template = _build_template(**dict(ENABLED_BOTH, **REMEDIATION_TARGETS))
    mutating_verbs = ('Update', 'Delete', 'Create', 'Put', 'Purge', 'Start', 'Stop', 'Retry',
                      'Register', 'Run', 'Execute', 'Modify', 'Restore', 'Reboot')
    read_only_exceptions = {'logs:StartQuery', 'logs:StopQuery', 'sts:GetCallerIdentity'}
    for logical_id in (C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE):
        for statement in _statements(_role(template, logical_id)):
            if statement['Effect'] != 'Allow':
                continue
            for action in _actions(statement):
                if action in read_only_exceptions or not any(v in action for v in mutating_verbs):
                    continue
                assert '*' not in _resources(statement), (
                    f'{logical_id} grants {action} on a wildcard resource')


def test_boundary_bounds_the_scoped_reads_instead_of_dropping_the_deny():
    """ The boundary opens with Allow *:*, so simply removing s3:GetObject / GetSecretValue from
        its deny list would permit them on everything. They are denied via NotResource instead.
    """
    template = _build_template(**dict(ENABLED_BOTH, **{
        Settings.S3_ENCRYPT_KEY_ID: TEST_KMS_KEY_ID,
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True,
    }))
    boundary = template['Resources']['C4IAMMainHumanAccessBoundary']['Properties']['PolicyDocument']
    carve_outs = {s['Sid']: s for s in boundary['Statement'] if 'NotResource' in s}
    assert set(carve_outs) == {'BoundS3ObjectReadsToApplicationBuckets',
                               'BoundSecretReadsToApplicationSecrets',
                               'BoundKmsUseToConfiguredEncryptionKey'}
    for statement in carve_outs.values():
        assert statement['Effect'] == 'Deny'
        assert statement['NotResource'], 'an empty NotResource would deny nothing'
        assert '*' not in statement['NotResource']
    assert 's3:GetObject' in _actions(carve_outs['BoundS3ObjectReadsToApplicationBuckets'])
    assert 'secretsmanager:GetSecretValue' in _actions(
        carve_outs['BoundSecretReadsToApplicationSecrets'])


def test_boundary_denies_the_scoped_reads_outright_when_there_is_nothing_to_carve_out():
    """ With no encryption key configured there is no legitimate target, so the deny is absolute. """
    template = _build_template(**ENABLED_BOTH)
    boundary = template['Resources']['C4IAMMainHumanAccessBoundary']['Properties']['PolicyDocument']
    kms_deny = next(s for s in boundary['Statement']
                    if s['Sid'] == 'BoundKmsUseToConfiguredEncryptionKey')
    assert 'NotResource' not in kms_deny
    assert kms_deny['Resource'] == '*'
    assert kms_deny['Effect'] == 'Deny'


def test_boundary_forbids_identity_and_infrastructure_administration():
    template = _build_template(**ENABLED_BOTH)
    boundary = template['Resources']['C4IAMMainHumanAccessBoundary']['Properties']['PolicyDocument']
    denied = {action for s in boundary['Statement'] if s['Effect'] == 'Deny'
              for action in _actions(s)}
    for action in ('iam:Create*', 'iam:Attach*', 'iam:PassRole', 'sso-admin:*', 'organizations:*',
                   'cloudformation:UpdateStack', 'cloudformation:ExecuteChangeSet',
                   'ecr:PutImage', 'lambda:UpdateFunctionCode', 'ec2:AuthorizeSecurityGroup*'):
        assert action in denied, f'boundary does not forbid {action}'
    # It is a boundary, not an administrative grant: the only Allow is the standard Allow *:*
    # that the deny statements then carve down.
    allows = [s for s in boundary['Statement'] if s['Effect'] == 'Allow']
    assert len(allows) == 1
    assert allows[0]['Action'] == '*'


# ---------------------------------------------------------------------------------------------
# Remediation is narrowly parameterized
# ---------------------------------------------------------------------------------------------

def test_remediation_has_no_mutating_power_until_target_arns_are_supplied():
    """ No derived-name, ENV_NAME or wildcard fallback: an unnamed environment is out of reach.
        This is what keeps a live (green) environment out of scope unless it is named on purpose.
    """
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    policy_names = [p['PolicyName'] for p in remediate['Policies']]
    assert 'HumanRemediateActionPolicy' not in policy_names
    for action in ('ecs:UpdateService', 'ecs:StopTask', 'sqs:ChangeMessageVisibility',
                   'sqs:PurgeQueue', 'states:StartExecution', 'codebuild:StartBuild'):
        assert not _statements_allowing(remediate, action), f'{action} granted with no target ARN'
    assert TEST_ENV_NAME not in _flat(remediate['Policies'])


@pytest.mark.parametrize('setting, action, expected_resource', [
    (Settings.HUMAN_ACCESS_REMEDIATE_SERVICE_ARNS, 'ecs:UpdateService', SERVICE_ARN),
    (Settings.HUMAN_ACCESS_REMEDIATE_QUEUE_ARNS, 'sqs:ChangeMessageVisibility', QUEUE_ARN),
    (Settings.HUMAN_ACCESS_REMEDIATE_STATE_MACHINE_ARNS, 'states:StartExecution',
     STATE_MACHINE_ARN),
    (Settings.HUMAN_ACCESS_REMEDIATE_CODEBUILD_ARNS, 'codebuild:StartBuild', CODEBUILD_ARN),
])
def test_each_remediation_capability_is_driven_by_its_own_supplied_arns(
        setting, action, expected_resource):
    remediate = _role(_build_template(**dict(ENABLED_BOTH, **{setting: expected_resource})),
                      C4IAM.REMEDIATE_ROLE)
    allowing = _statements_allowing(remediate, action)
    assert len(allowing) == 1
    assert _resources(allowing[0]) == [expected_resource]
    # Every write is region-pinned and gated on a live MFA session.
    condition = allowing[0]['Condition']
    assert condition['Bool'] == {'aws:MultiFactorAuthPresent': 'true'}
    assert condition['StringEquals'] == {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}


def test_stop_task_is_confined_to_the_supplied_cluster():
    remediate = _role(_build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_REMEDIATE_CLUSTER_ARNS: CLUSTER_ARN})), C4IAM.REMEDIATE_ROLE)
    allowing = _statements_allowing(remediate, 'ecs:StopTask')
    assert len(allowing) == 1
    assert _resources(allowing[0]) == ['arn:aws:ecs:us-east-1:123456789:task/some-cluster/*']
    assert allowing[0]['Condition']['ArnEquals'] == {'ecs:cluster': [CLUSTER_ARN]}


def test_sqs_purge_requires_its_own_explicit_flag_on_top_of_supplied_queues():
    """ PurgeQueue is irreversible, so having queue ARNs is not enough to get it. """
    with_queues = dict(ENABLED_BOTH, **{Settings.HUMAN_ACCESS_REMEDIATE_QUEUE_ARNS: QUEUE_ARN})

    remediate = _role(_build_template(**with_queues), C4IAM.REMEDIATE_ROLE)
    assert not _statements_allowing(remediate, 'sqs:PurgeQueue')
    # The reversible queue action is still available, i.e. purge is genuinely split out.
    assert _statements_allowing(remediate, 'sqs:ChangeMessageVisibility')

    remediate = _role(_build_template(**dict(with_queues, **{
        Settings.HUMAN_ACCESS_REMEDIATE_ALLOW_QUEUE_PURGE: True})), C4IAM.REMEDIATE_ROLE)
    allowing = _statements_allowing(remediate, 'sqs:PurgeQueue')
    assert len(allowing) == 1
    assert _resources(allowing[0]) == [QUEUE_ARN]


def test_purge_flag_alone_grants_nothing_without_queue_arns():
    remediate = _role(_build_template(**dict(ENABLED_BOTH, **{
        Settings.HUMAN_ACCESS_REMEDIATE_ALLOW_QUEUE_PURGE: True})), C4IAM.REMEDIATE_ROLE)
    assert not _statements_allowing(remediate, 'sqs:PurgeQueue')


def test_remediation_reads_are_narrower_than_diagnostic_reads():
    """ Keeps CloudTrail separable into "someone was looking" and "someone was changing". """
    remediate = _role(_build_template(**ENABLED_BOTH), C4IAM.REMEDIATE_ROLE)
    for action in ('secretsmanager:GetSecretValue', 's3:GetObject', 'kms:Decrypt'):
        assert not _statements_allowing(remediate, action)
        assert action in _denied_actions(remediate)


# ---------------------------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------------------------

def test_human_roles_do_not_reuse_the_ecs_runtime_role_policies():
    """ dev_user_role() shares four inline policy objects with the ECS runtime role, which is what
        makes human access a superset of runtime privilege. These roles must not repeat that.
    """
    template = _build_template(**dict(ENABLED_BOTH, **REMEDIATION_TARGETS))
    ecs_policy_names = {p['PolicyName']
                        for p in _role(template, 'CGAPECSRole')['Policies']}
    for logical_id in (C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE):
        human_policy_names = {p['PolicyName'] for p in _role(template, logical_id)['Policies']}
        assert not (human_policy_names & ecs_policy_names)
        # None of the runtime role's blanket grants may appear.
        rendered = _flat(_role(template, logical_id)['Policies'])
        for blanket in ('"ecs:*"', '"es:*"', '"sqs:*"', '"elasticloadbalancing:*"'):
            assert blanket not in rendered, f'{logical_id} reuses the blanket grant {blanket}'


@pytest.mark.parametrize('logical_id', [C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE])
def test_every_role_denies_activity_outside_the_deployment_region(logical_id):
    role = _role(_build_template(**ENABLED_BOTH), logical_id)
    region_denies = [s for s in _statements(role)
                     if s['Effect'] == 'Deny' and 'NotAction' in s]
    assert len(region_denies) == 1
    assert region_denies[0]['Condition'] == {
        'StringNotEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}


def test_policies_fit_within_aws_iam_size_limits():
    """ Guards against a future addition silently breaking the deploy: AWS caps a role's inline
        policies at 10240 characters in total, and a managed policy document at 6144.
    """
    template = _build_template(**dict(ENABLED_BOTH, **dict(REMEDIATION_TARGETS, **{
        Settings.S3_ENCRYPT_KEY_ID: TEST_KMS_KEY_ID,
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True,
        Settings.HUMAN_ACCESS_REMEDIATE_ALLOW_QUEUE_PURGE: True,
    })))
    for logical_id in (C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE):
        size = sum(len(json.dumps(p['PolicyDocument'], separators=(',', ':')))
                   for p in _role(template, logical_id)['Policies'])
        assert size <= 10240, f'{logical_id} inline policies are {size} characters'
    boundary = template['Resources']['C4IAMMainHumanAccessBoundary']['Properties']['PolicyDocument']
    boundary_size = len(json.dumps(boundary, separators=(',', ':')))
    assert boundary_size <= 6144, f'boundary policy is {boundary_size} characters'


def test_enabled_template_adds_only_the_expected_resources():
    template = _build_template(**dict(ENABLED_BOTH, **REMEDIATION_TARGETS))
    added = set(template['Resources']) - PRE_EXISTING_RESOURCES
    assert added == {C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE, 'C4IAMMainHumanAccessBoundary'}
    added_outputs = set(template['Outputs']) - PRE_EXISTING_OUTPUTS
    assert added_outputs == {f'C4IAMMain{C4IAM.DIAGNOSE_ROLE}Name',
                             f'C4IAMMain{C4IAM.REMEDIATE_ROLE}Name'}
    # The opt-in outputs are not exported: no other stack should depend on this feature.
    for output in added_outputs:
        assert 'Export' not in template['Outputs'][output]
