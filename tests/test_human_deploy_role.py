"""
Offline tests for the opt-in deployment role (C4IAM.human_deploy_role).

What makes these tests more than a restatement of src/parts/iam.py:

  * tests/data/aws_iam_deploy_reference.json is official AWS data, not derived from this
    repository: the CloudFormation resource-provider "handlers" permissions for every resource
    type the templates use, and the AWS Policy Generator action/condition-key catalogue. See its
    "_source" entry for the URLs and retrieval date.
  * The resource types are taken from templates synthesized here from the real stack classes,
    so adding a resource type without deciding its permissions fails a test.
  * Positive/negative scenarios are evaluated by a small IAM evaluator (explicit deny wins,
    wildcards, NotResource, the condition operators these policies use) rather than by looking
    for strings, and the AWS CLI's own deploy/package code is driven against stubbed clients to
    get the API calls it actually makes.

Nothing here contacts AWS. These are static checks of the generated policy, not an IAM simulator
run against a real account, and they do not prove a live deployment succeeds.
"""
import contextlib
import fnmatch
import importlib
import io
import json
import os
import re
import sys
from unittest import mock

import botocore.session
import pytest
from botocore.stub import Stubber

from src import base
from src.base import ConfigManager, registered_stack_class
from src.constants import Settings
from src.part import C4Account
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.iam import C4IAM
from src.stack import BaseC4FoursightStack
from src.commands.identity_swap import C4IdentitySwap
from .test_human_access_roles import (
    ALICE, BOB, ENABLED_BOTH, PRE_EXISTING_OUTPUTS, PRE_EXISTING_RESOURCES, README,
    _actions, _as_list, _build_template, _flat, _role,
)

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')
REFERENCE = json.load(io.open(os.path.join(os.path.dirname(__file__), 'data',
                                           'aws_iam_deploy_reference.json')))
REGION = 'us-east-1'
ACCOUNT = '123456789012'
OTHER_ACCOUNT = '210987654321'

DEPLOYERS = 'arn:aws:iam::123456789012:role/ApprovedDeployers'
ENABLED_DEPLOY = {
    Settings.HUMAN_ACCESS_DEPLOY_ENABLED: True,
    Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: DEPLOYERS,
}
DEPLOY_POLICY_IDS = ('C4IAMMainInfraDeployStackPolicy', 'C4IAMMainInfraDeployComputePolicy',
                     'C4IAMMainInfraDeployDataPolicy')


# ---------------------------------------------------------------------------------------------
# Helpers: rendering and a minimal IAM evaluator
# ---------------------------------------------------------------------------------------------

def _resolve(value):
    """ Renders CloudFormation intrinsics used in these policies to concrete strings. """
    if isinstance(value, dict):
        if value == {'Ref': 'AWS::Region'}:
            return REGION
        if value == {'Ref': 'AWS::AccountId'}:
            return ACCOUNT
        if 'Fn::Join' in value:
            separator, parts = value['Fn::Join']
            return separator.join(_resolve(part) for part in parts)
        return {key: _resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve(item) for item in value]
    return value


def _deploy_template(**overrides) -> dict:
    return _build_template(**dict(ENABLED_DEPLOY, **overrides))


def _deploy_documents(template: dict) -> list:
    """ [(name, policy document)] for the deploy role: its managed policies then its inline one. """
    role = _role(template, C4IAM.DEPLOY_ROLE)
    documents = []
    for reference in role['ManagedPolicyArns']:
        logical_id = reference['Ref']
        documents.append((logical_id, template['Resources'][logical_id]['Properties']['PolicyDocument']))
    for policy in role.get('Policies', []):
        documents.append((policy['PolicyName'], policy['PolicyDocument']))
    return documents


def _deploy_statements(template: dict = None) -> list:
    template = template or _deploy_template()
    return [statement for _, document in _deploy_documents(template)
            for statement in document['Statement']]


def _match(pattern: str, value: str) -> bool:
    return fnmatch.fnmatchcase(value.lower(), pattern.lower())


def _condition_holds(condition: dict, context: dict) -> bool:
    for operator, tests in condition.items():
        if_exists = operator.endswith('IfExists')
        base = operator[:-len('IfExists')] if if_exists else operator
        for key, expected in tests.items():
            expected = [str(item) for item in _as_list(expected)]
            present = key in context
            if base == 'Null':
                if (expected[0] == 'true') != (not present):
                    return False
                continue
            if not present:
                if if_exists:
                    continue
                if base.startswith('StringNot') or base.startswith('ArnNot'):
                    continue  # negated operators match an absent key
                return False
            actual = [str(item) for item in _as_list(context[key])]
            if base in ('StringEquals', 'ArnEquals'):
                ok = any(a == e for a in actual for e in expected)
            elif base in ('StringLike', 'ArnLike'):
                ok = any(_match(e, a) for a in actual for e in expected)
            elif base == 'StringNotEquals':
                ok = not any(a == e for a in actual for e in expected)
            elif base == 'Bool':
                ok = actual[0].lower() == expected[0].lower()
            elif base == 'NumericLessThan':
                ok = float(actual[0]) < float(expected[0])
            else:
                raise AssertionError(f'evaluator does not implement {operator}')
            if not ok:
                return False
    return True


def _statement_applies(statement: dict, action: str, resource: str, context: dict) -> bool:
    statement = _resolve(statement)
    if 'Action' in statement:
        if not any(_match(pattern, action) for pattern in _as_list(statement['Action'])):
            return False
    elif any(_match(pattern, action) for pattern in _as_list(statement['NotAction'])):
        return False
    if 'Resource' in statement:
        if not any(_match(pattern, resource) for pattern in _as_list(statement['Resource'])):
            return False
    elif any(_match(pattern, resource) for pattern in _as_list(statement['NotResource'])):
        return False
    return _condition_holds(statement.get('Condition', {}), context)


def _decide(action: str, resource: str = '*', context: dict = None, statements: list = None) -> str:
    """ 'allow', 'deny' (explicit) or 'implicit-deny' for one request against the deploy role. """
    statements = statements if statements is not None else _deploy_statements()
    context = dict({'aws:RequestedRegion': REGION}, **(context or {}))
    applicable = [s for s in statements if _statement_applies(s, action, resource, context)]
    if any(s['Effect'] == 'Deny' for s in applicable):
        return 'deny'
    if any(s['Effect'] == 'Allow' for s in applicable):
        return 'allow'
    return 'implicit-deny'


def _allowed_somewhere(action: str, statements: list) -> bool:
    """ Action-level check: some Allow names it, and no Deny with an unconditional '*' resource
        names it. Resource/condition scoping is exercised by the scenario tests below.
    """
    allowed = any(s['Effect'] == 'Allow' and any(_match(p, action) for p in _as_list(s['Action']))
                  for s in statements)
    blanket_denied = any(
        s['Effect'] == 'Deny' and s.get('Resource') == '*' and 'Condition' not in s
        and 'Action' in s and any(_match(p, action) for p in _as_list(s['Action']))
        for s in statements)
    return allowed and not blanket_denied


def _generated_name(stack: str, logical_id: str) -> str:
    """ CloudFormation's generated physical name shape for IAM resources without an explicit name. """
    return f'{stack}-{logical_id}-1A2B3C4D5E6F7'


# ---------------------------------------------------------------------------------------------
# Synthesized templates (the resource types the role must be able to deploy)
# ---------------------------------------------------------------------------------------------

@contextlib.contextmanager
def _registered_stacks():
    """ Registers the real stack creators only for the duration of the block. Importing them at
        module level would leave the global registry populated for unrelated tests (for example
        src/tests/test_base.py, which expects to start from an empty registry).
    """
    modules = ('src.stacks.alpha_stacks', 'src.cli')
    preloaded = {name: sys.modules.get(name) for name in modules}
    with mock.patch.dict(base.REGISTERED_STACKS, clear=True), \
            mock.patch.dict(base.REGISTERED_STACK_CLASSES, clear=True):
        try:
            for name in modules:
                if preloaded[name] is None:
                    importlib.import_module(name)
                else:
                    importlib.reload(preloaded[name])
            yield sys.modules['src.cli']
        finally:
            for name, module in preloaded.items():
                if module is None:
                    sys.modules.pop(name, None)


# Values the CI dummy config lacks but some stacks need in order to synthesize.
SYNTHESIS_EXTRAS = {
    'sentieon.ssh_key': 'offline-key', 'jupyterhub.ssh_key': 'offline-key',
    'higlass.ssh_key': 'offline-key', 'GITHUB_PERSONAL_ACCESS_TOKEN': 'offline-token',
    'codebuild.repo_url': 'https://github.com/example/offline',
    Settings.FOURFRONT_VPC: 'vpc-0123456789abcdef0', Settings.FOURFRONT_VPC_CIDR: '10.0.0.0/16',
    Settings.FOURFRONT_PRIMARY_SUBNET: 'subnet-0123456789abcdef0',
    Settings.FOURFRONT_SECONDARY_SUBNET: 'subnet-0123456789abcdef1',
    Settings.FOURFRONT_RDS_SECURITY_GROUP: 'sg-0123456789abcdef0',
    Settings.FOURFRONT_HTTPS_SECURITY_GROUP: 'sg-0123456789abcdef1',
}

# The Foursight stack is a Chalice SAM package (`chalice package --pkg-format cloudformation`)
# which needs deployed exports to build, so it is not synthesized here. Its resources after the
# AWS::Serverless-2016-10-31 transform: the Chalice DefaultRole, the functions, their schedules
# (Events::Rule + Lambda::Permission) and the REST API.
FOURSIGHT_RESOURCE_TYPES = {
    'AWS::IAM::Role', 'AWS::Lambda::Function', 'AWS::Lambda::Permission', 'AWS::Events::Rule',
    'AWS::ApiGateway::RestApi', 'AWS::ApiGateway::Deployment', 'AWS::ApiGateway::Stage',
}


@pytest.fixture(scope='module')
def synthesized_templates():
    """ {stack name: template} for every non-Foursight, non-blue/green stack under the CI config.
        (Blue/green synthesizes the same resource types; it needs app.deploy set at import time.)
    """
    config = dict(ConfigManager.singleton()._get_config(), **SYNTHESIS_EXTRAS)
    account = C4Account(account_number=ACCOUNT, creds_file='/dev/null')
    templates = {}
    with _registered_stacks(), \
            mock.patch.object(ConfigManager.singleton(), '_CACHED_CONFIG', config), \
            mock.patch.object(ConfigManager, 'find_stack_output', return_value='offline-value'), \
            mock.patch.object(ConfigManager, 'find_stack_outputs',
                              return_value=['subnet-0123456789abcdef0', 'subnet-0123456789abcdef1']), \
            mock.patch.object(ApplicationConfigurationSecrets, 'get_es_url',
                              return_value='offline.example.invalid'):
        for kind, creators in base.REGISTERED_STACKS.items():
            for name, creator in creators.items():
                cls = registered_stack_class(name, kind=kind)
                if issubclass(cls, BaseC4FoursightStack) or 'blue_green' in name:
                    continue
                stack = creator(account=account)
                templates[f'{kind}/{name}'] = (stack.name.stack_name, stack.template.to_dict())
    assert len(templates) >= 14
    return templates


def _template_resource_types(templates) -> set:
    return {resource['Type'] for _, template in templates.values()
            for resource in template['Resources'].values()}


# ---------------------------------------------------------------------------------------------
# 1. Opt-in, parity and trust
# ---------------------------------------------------------------------------------------------

def test_deploy_role_is_absent_by_default_and_with_only_the_older_roles_enabled():
    assert set(_build_template()['Resources']) == PRE_EXISTING_RESOURCES
    template = _build_template(**ENABLED_BOTH)
    assert not [r for r in template['Resources'] if 'Deploy' in r]
    assert not [o for o in template['Outputs'] if 'Deploy' in o]


def test_existing_principals_never_gain_deployment_authority():
    """ Enabling deploy without its own principal list creates nothing - the diagnose/remediate
        principal lists are never reused.
    """
    template = _build_template(**dict(ENABLED_BOTH, **{Settings.HUMAN_ACCESS_DEPLOY_ENABLED: True}))
    assert C4IAM.DEPLOY_ROLE not in template['Resources']
    assert not [r for r in template['Resources'] if 'InfraDeploy' in r]
    # ... and a principal list without the enable flag does nothing either.
    template = _build_template(**{Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: DEPLOYERS})
    assert set(template['Resources']) == PRE_EXISTING_RESOURCES


def test_older_role_templates_are_unchanged_when_deploy_is_enabled_alongside():
    without = _build_template(**ENABLED_BOTH)
    with_deploy = _build_template(**dict(ENABLED_BOTH, **ENABLED_DEPLOY))
    for logical_id, resource in without['Resources'].items():
        assert with_deploy['Resources'][logical_id] == resource


def test_enabling_deploy_adds_exactly_the_role_its_policies_and_its_outputs():
    template = _deploy_template()
    assert set(template['Resources']) - PRE_EXISTING_RESOURCES == {C4IAM.DEPLOY_ROLE, *DEPLOY_POLICY_IDS}
    added_outputs = set(template['Outputs']) - PRE_EXISTING_OUTPUTS
    assert added_outputs == {f'C4IAMMain{C4IAM.DEPLOY_ROLE}Name', 'C4IAMMainHumanDeployRoleArn'}
    assert 'Export' not in template['Outputs'][f'C4IAMMain{C4IAM.DEPLOY_ROLE}Name']
    # The ARN is exported for exactly one consumer: the datastore key policy.
    arn_output = template['Outputs']['C4IAMMainHumanDeployRoleArn']
    assert arn_output['Value'] == {'Fn::GetAtt': [C4IAM.DEPLOY_ROLE, 'Arn']}
    assert arn_output['Export'] == {'Name': {'Fn::Sub': '${AWS::StackName}-HumanDeployRoleArn'}}
    # The deploy role does not share (or require) the diagnose/remediate boundary.
    assert 'C4IAMMainHumanAccessBoundary' not in template['Resources']
    assert 'PermissionsBoundary' not in _role(template, C4IAM.DEPLOY_ROLE)


def test_deploy_trust_is_enumerated_mfa_and_source_identity_gated():
    role = _role(_build_template(**dict(ENABLED_DEPLOY, **{
        Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: f'{ALICE},{BOB}'})), C4IAM.DEPLOY_ROLE)
    trust = role['AssumeRolePolicyDocument']
    allow, deny = trust['Statement']
    assert allow['Principal'] == {'AWS': [ALICE, BOB]}
    assert allow['Condition']['Bool'] == {'aws:MultiFactorAuthPresent': 'true'}
    assert deny['Effect'] == 'Deny' and deny['Condition'] == {'Null': {'sts:SourceIdentity': 'true'}}
    assert ':root' not in _flat(trust) and 'AWS::AccountId' not in _flat(trust)
    assert role['MaxSessionDuration'] == 3600


@pytest.mark.parametrize('principals', [
    'arn:aws:iam::123456789012:root', '123456789012', '*', 'arn:aws:iam::*:role/x',
    'arn:aws:sts::123456789012:assumed-role/Deployers/alice',
])
def test_deploy_trust_rejects_root_wildcard_and_session_principals(principals):
    with pytest.raises(ValueError):
        _deploy_template(**{Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: principals})


def test_deploy_role_is_not_built_without_principals():
    template = _build_template(**{Settings.HUMAN_ACCESS_DEPLOY_ENABLED: True,
                                  Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: ' , '})
    assert set(template['Resources']) == PRE_EXISTING_RESOURCES


# ---------------------------------------------------------------------------------------------
# 2. Validity against official AWS data, quotas and references
# ---------------------------------------------------------------------------------------------

def _all_human_access_statements() -> list:
    template = _build_template(**dict(ENABLED_BOTH, **ENABLED_DEPLOY, **{
        Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT: True}))
    statements = _deploy_statements(template)
    for logical_id in (C4IAM.DIAGNOSE_ROLE, C4IAM.REMEDIATE_ROLE):
        statements += [s for p in _role(template, logical_id)['Policies']
                       for s in p['PolicyDocument']['Statement']]
    statements += template['Resources']['C4IAMMainHumanAccessBoundary']['Properties'][
        'PolicyDocument']['Statement']
    return statements


def test_every_action_in_every_human_access_policy_is_a_real_iam_action():
    catalogue = REFERENCE['iam_actions']
    unknown = []
    for statement in _all_human_access_statements():
        for pattern in _actions(statement):
            if pattern == '*':
                continue
            prefix, name = pattern.split(':', 1)
            assert prefix in catalogue, f'unknown service prefix in {pattern}'
            if name == '*':
                continue
            if not any(fnmatch.fnmatchcase(a, name) for a in catalogue[prefix]):
                unknown.append(pattern)
    assert not unknown, f'not in the AWS action catalogue: {sorted(set(unknown))}'


def test_every_condition_key_is_a_real_condition_key():
    known = set(REFERENCE['global_condition_keys'])
    for keys in REFERENCE['condition_keys'].values():
        known |= set(keys)
    used = {key for s in _all_human_access_statements()
            for test in s.get('Condition', {}).values() for key in test}
    assert used and used <= known, sorted(used - known)


def test_deploy_policies_fit_iam_quotas():
    template = _deploy_template()
    role = _role(template, C4IAM.DEPLOY_ROLE)
    for name, document in _deploy_documents(template):
        rendered = re.sub(r'\s', '', json.dumps(_resolve(document)))
        limit = 10240 if name == 'HumanDeployGuardrailPolicy' else 6144
        assert len(rendered) <= limit, f'{name} is {len(rendered)} characters'
    assert len(role['ManagedPolicyArns']) <= 10
    assert all(set(ref) == {'Ref'} and ref['Ref'] in template['Resources']
               for ref in role['ManagedPolicyArns'])


def test_stack_name_leaves_room_for_untruncated_protected_role_names():
    """ The guardrail matches generated names by logical-id token. The IAM stack name must leave
        enough of the 64-character role-name limit that the token is never truncated away.
    """
    with pytest.raises(ValueError):
        C4IAM.check_protected_names_fit('c4-iam-a-very-long-ecosystem-name-here-stack')
    C4IAM.check_protected_names_fit('c4-iam-main-stack')


# ---------------------------------------------------------------------------------------------
# 3. Breadth: no admin, no write wildcards, wildcard resources only where unavoidable
# ---------------------------------------------------------------------------------------------

def test_no_admin_or_service_wide_grants():
    for statement in _deploy_statements():
        if statement['Effect'] != 'Allow':
            continue
        assert 'NotAction' not in statement and 'NotResource' not in statement
        for action in _actions(statement):
            assert action != '*' and not action.endswith(':*'), action
            if '*' in action:
                raise AssertionError(f'wildcard action {action} in an Allow')


def test_wildcard_resources_only_in_declared_statements():
    for statement in _deploy_statements():
        if statement['Effect'] == 'Allow' and '*' in _as_list(statement['Resource']):
            assert statement['Sid'] in C4IAM.DEPLOY_WILDCARD_SIDS, statement['Sid']
            assert statement['Condition'] == {'StringEquals': {'aws:RequestedRegion': {'Ref': 'AWS::Region'}}}


def test_no_managed_aws_policy_or_administrator_access_is_attached_to_the_role():
    role = _role(_deploy_template(), C4IAM.DEPLOY_ROLE)
    assert all('arn:aws:iam::aws:policy' not in _flat(ref) for ref in role['ManagedPolicyArns'])


# ---------------------------------------------------------------------------------------------
# 4. Coverage of what CloudFormation needs, from AWS's own handler declarations
# ---------------------------------------------------------------------------------------------

# Handler permissions deliberately not granted, with the reason. Every entry must be exercised,
# and none may be allowed, so this list cannot go stale or contradict the policy.
INVALID = 'not an IAM action in the AWS catalogue (handler metadata error)'
UNUSED = 'only for a property/feature these templates never set'
DATA = 'destroys a data-bearing resource: denied, so replacement/removal needs an administrator'
GUARD = 'identity administration this role must not perform'
NOT_GRANTED = {
    's3:REST.PUT.OBJECT': INVALID, 'es:UpdateDomain': INVALID,
    's3:DeleteBucketEncryption': INVALID, 's3:DeleteBucketLifecycle': INVALID,
    'rds:DeleteDBInstance': DATA, 'rds:CreateDBSnapshot': DATA, 'es:DeleteDomain': DATA,
    's3:DeleteBucket': DATA, 's3:DeleteObject': DATA, 'sqs:DeleteQueue': DATA,
    'secretsmanager:DeleteSecret': DATA, 'kms:ScheduleKeyDeletion': DATA, 'kms:DisableKey': DATA,
    'ecr:DeleteRepository': DATA, 'logs:DeleteLogGroup': DATA,
    'elasticache:DeleteReplicationGroup': DATA, 'elasticache:CreateSnapshot': DATA,
    'secretsmanager:UpdateSecret': 'would rewrite a filled SecretString; denied (see docs)',
    'iam:AttachUserPolicy': GUARD,
    'iam:DetachUserPolicy': GUARD, 'iam:AddUserToGroup': GUARD, 'iam:RemoveUserFromGroup': GUARD,
    'iam:CreateLoginProfile': GUARD, 'iam:UpdateLoginProfile': GUARD,
    'iam:DeleteLoginProfile': GUARD, 'iam:DeleteAccessKey': GUARD,
    'iam:PutRolePermissionsBoundary': GUARD, 'iam:DeleteRolePermissionsBoundary': GUARD,
    'iam:PutUserPermissionsBoundary': GUARD, 'iam:DeleteUserPermissionsBoundary': GUARD,
    'iam:UpdateUser': GUARD, 'iam:ListUserTags': GUARD, 'iam:ListRoles': UNUSED,
    'kms:CreateGrant': UNUSED, 'kms:RetireGrant': UNUSED, 'kms:Encrypt': UNUSED,
    'kms:EnableKey': UNUSED, 'kms:EnableKeyRotation': UNUSED, 'kms:DisableKeyRotation': UNUSED,
    'ecs:PutAccountSetting': 'account-wide ECS setting; never needed for these clusters',
    'ecs:PutAccountSettingDefault': 'account-wide ECS setting; never needed for these clusters',
    'ec2:AcceptAddressTransfer': UNUSED, 'ec2:AssignPrivateNatGatewayAddress': UNUSED,
    'ec2:AssociateNatGatewayAddress': UNUSED, 'ec2:DisassociateNatGatewayAddress': UNUSED,
    'ec2:UnassignPrivateNatGatewayAddress': UNUSED, 'ec2:AssociateSubnetCidrBlock': UNUSED,
    'ec2:DisassociateSubnetCidrBlock': UNUSED, 'ec2:CreateVpcEncryptionControl': UNUSED,
    'ec2:DescribeVpcEncryptionControls': UNUSED, 'ec2:ModifyVpcTenancy': UNUSED,
    'ec2:AttachVpnGateway': UNUSED, 'ec2:DetachVpnGateway': UNUSED,
    'ec2:DescribeVpnGateways': UNUSED, 'ec2:AssociateIamInstanceProfile': UNUSED,
    'ec2:DisassociateIamInstanceProfile': UNUSED, 'ec2:ReplaceIamInstanceProfileAssociation': UNUSED,
    'ec2:DescribeIamInstanceProfileAssociations': UNUSED, 'ec2:AttachVolume': UNUSED,
    'ec2:DetachVolume': UNUSED, 'ec2:ModifyInstanceCreditSpecification': UNUSED,
    'ec2:ModifyInstancePlacement': UNUSED, 'ec2:ModifyPrivateDnsNameOptions': UNUSED,
    'ec2:ModifyInstanceMaintenanceOptions': UNUSED, 'ec2:ModifyInstanceMetadataOptions': UNUSED,
    'ec2:MonitorInstances': UNUSED, 'ec2:UnmonitorInstances': UNUSED,
    'ec2:DescribeLaunchTemplateVersions': UNUSED, 'ec2:DescribeIpamPools': UNUSED,
    'ssm:CreateAssociation': UNUSED, 'ssm:DeleteAssociation': UNUSED,
    'ssm:DescribeAssociation': UNUSED, 'ssm:ListAssociations': UNUSED,
    'vpc-lattice:CreateServiceNetworkVpcEndpointAssociation': UNUSED,
    'vpc-lattice:DescribeServiceNetworkVpcEndpointAssociation': INVALID,
    'vpce:AllowMultiRegion': UNUSED,
    'elasticloadbalancing:ModifyCapacityReservation': UNUSED,
    'elasticloadbalancing:DescribeCapacityReservation': UNUSED,
    'elasticloadbalancing:ModifyIpPools': UNUSED, 'cognito-idp:DescribeUserPoolClient': UNUSED,
    'elasticache:ModifyReplicationGroupShardConfiguration': UNUSED,
    'firehose:PutRecord': UNUSED, 'firehose:PutRecordBatch': UNUSED,
    'firehose:TagDeliveryStream': UNUSED,
    'logs:CreateLogDelivery': UNUSED, 'logs:DeleteLogDelivery': UNUSED,
    'logs:GetLogDelivery': UNUSED, 'logs:ListLogDeliveries': UNUSED,
    'logs:UpdateLogDelivery': UNUSED, 'logs:CreateLogStream': UNUSED, 'logs:PutLogEvents': UNUSED,
    'logs:PutDataProtectionPolicy': UNUSED, 'logs:DeleteDataProtectionPolicy': UNUSED,
    'logs:PutIndexPolicy': UNUSED, 'logs:DeleteIndexPolicy': UNUSED,
    'logs:PutResourcePolicy': UNUSED, 'logs:DeleteResourcePolicy': UNUSED,
    'logs:PutBearerTokenAuthentication': UNUSED, 'logs:AssociateKmsKey': UNUSED,
    'logs:DisassociateKmsKey': UNUSED, 'logs:PutLogGroupDeletionProtection': UNUSED,
    'rds:AddRoleToDBInstance': UNUSED, 'rds:RemoveRoleFromDBInstance': UNUSED,
    'rds:CreateDBInstanceReadReplica': UNUSED, 'rds:PromoteReadReplica': UNUSED,
    'rds:RestoreDBInstanceFromDBSnapshot': UNUSED, 'rds:RestoreDBInstanceToPointInTime': UNUSED,
    'rds:StartDBInstanceAutomatedBackupsReplication': UNUSED,
    'rds:StopDBInstanceAutomatedBackupsReplication': UNUSED,
    'secretsmanager:ReplicateSecretToRegions': UNUSED,
    'secretsmanager:RemoveRegionsFromReplication': UNUSED,
    'redshift:DescribeClusters': UNUSED, 'redshift-serverless:GetNamespace': UNUSED,
    'redshift-serverless:ListWorkgroups': UNUSED, 'docdb-elastic:GetCluster': UNUSED,
    'codebuild:CreateWebhook': UNUSED, 'codebuild:UpdateWebhook': UNUSED,
    'codebuild:DeleteWebhook': UNUSED, 'codebuild:UpdateProjectVisibility': UNUSED,
    'ecr:PutLifecyclePolicy': UNUSED, 'ecr:DeleteLifecyclePolicy': UNUSED,
    'ecr:PutImageTagMutability': UNUSED,
    'lambda:AssociateRuntimeAlias': INVALID, 'lambda:PassCapacityProvider': UNUSED,
    'lambda:GetCodeSigningConfig': UNUSED, 'lambda:PutFunctionCodeSigningConfig': UNUSED,
    'lambda:DeleteFunctionCodeSigningConfig': UNUSED, 'lambda:PutFunctionConcurrency': UNUSED,
    'lambda:DeleteFunctionConcurrency': UNUSED, 'lambda:PutFunctionRecursionConfig': UNUSED,
    'lambda:PutFunctionScalingConfig': UNUSED, 'lambda:PutRuntimeManagementConfig': UNUSED,
    'lambda:PublishVersion': UNUSED, 'elasticfilesystem:DescribeMountTargets': UNUSED,
    's3files:ListMountTargets': UNUSED,
    's3:CreateBucketMetadataTableConfiguration': UNUSED,
    's3:DeleteBucketMetadataTableConfiguration': UNUSED,
    's3:UpdateBucketMetadataAnnotationTableConfiguration': UNUSED,
    's3:UpdateBucketMetadataInventoryTableConfiguration': UNUSED,
    's3:UpdateBucketMetadataJournalTableConfiguration': UNUSED,
    's3:PutAccelerateConfiguration': UNUSED, 's3:PutAnalyticsConfiguration': UNUSED,
    's3:DeleteBucketAnalyticsConfiguration': INVALID, 's3:PutBucketAbac': UNUSED,
    's3:PutBucketCORS': UNUSED, 's3:DeleteBucketCors': INVALID,
    's3:PutBucketDefaultStorageClass': INVALID, 's3:GetBucketDefaultStorageClass': INVALID,
    's3:PutBucketLogging': UNUSED, 's3:PutBucketNotification': UNUSED,
    's3:PutBucketObjectLockConfiguration': UNUSED, 's3:PutObjectLockConfiguration': INVALID,
    's3:PutBucketReplication': INVALID, 's3:PutReplicationConfiguration': UNUSED,
    's3:DeleteBucketReplication': INVALID, 's3:PutBucketWebsite': UNUSED,
    's3:DeleteBucketWebsite': UNUSED, 's3:PutIntelligentTieringConfiguration': UNUSED,
    's3:PutInventoryConfiguration': UNUSED, 's3:PutMetricsConfiguration': UNUSED,
    's3:DeleteBucketMetricsConfiguration': INVALID, 's3:PutObjectAcl': UNUSED,
    's3:TagResource': UNUSED, 's3:UntagResource': UNUSED,
}
NOT_GRANTED_PREFIXES = {'s3tables:': UNUSED}

# AWS::Elasticsearch::Domain (datastore_slim) has no published handler schema; these are the
# Service Authorization Reference actions for the legacy Elasticsearch configuration APIs.
LEGACY_ELASTICSEARCH_ACTIONS = [
    'es:CreateElasticsearchDomain', 'es:UpdateElasticsearchDomainConfig',
    'es:DescribeElasticsearchDomain', 'es:DescribeElasticsearchDomainConfig',
    'es:UpgradeElasticsearchDomain', 'es:AddTags', 'es:ListTags', 'es:RemoveTags',
]


def _not_granted_reason(action):
    if action in NOT_GRANTED:
        return NOT_GRANTED[action]
    return next((reason for prefix, reason in NOT_GRANTED_PREFIXES.items()
                 if action.startswith(prefix)), None)


def test_synthesized_resource_types_all_have_official_handler_data(synthesized_templates):
    types = _template_resource_types(synthesized_templates) | FOURSIGHT_RESOURCE_TYPES
    missing = sorted(t for t in types if t not in REFERENCE['handler_permissions'])
    assert not missing, f'add these to tests/data/aws_iam_deploy_reference.json: {missing}'


def test_every_cloudformation_handler_permission_is_granted_or_explicitly_excluded(
        synthesized_templates):
    statements = _deploy_statements()
    types = _template_resource_types(synthesized_templates) | FOURSIGHT_RESOURCE_TYPES
    missing, used_exclusions = {}, set()
    for resource_type in sorted(types):
        handlers = REFERENCE['handler_permissions'][resource_type]
        required = (LEGACY_ELASTICSEARCH_ACTIONS if handlers is None
                    else {a for operation in handlers.values() for a in operation})
        for action in sorted(required):
            if _not_granted_reason(action):
                used_exclusions.add(action)
                continue
            if not _allowed_somewhere(action, statements):
                missing.setdefault(resource_type, []).append(action)
    assert not missing, f'handler permissions neither granted nor excluded: {missing}'
    stale = set(NOT_GRANTED) - used_exclusions
    assert not stale, f'exclusions no handler requires any more: {sorted(stale)}'


def test_excluded_handler_permissions_are_really_not_granted():
    statements = _deploy_statements()
    granted = [a for a in NOT_GRANTED if _allowed_somewhere(a, statements)]
    assert not granted, f'listed as not granted but allowed: {granted}'


def test_invalid_handler_names_are_absent_from_the_aws_catalogue():
    catalogue = REFERENCE['iam_actions']
    for action, reason in NOT_GRANTED.items():
        prefix, name = action.split(':', 1)
        assert (name in catalogue.get(prefix, [])) == (reason != INVALID), action


def test_managed_policies_attached_by_deployable_roles_are_exactly_the_allowed_list(
        synthesized_templates):
    attached = set()
    for _, template in synthesized_templates.values():
        for logical_id, resource in template['Resources'].items():
            if resource['Type'] == 'AWS::IAM::Role' and 'DevRole' not in logical_id:
                attached |= set(resource['Properties'].get('ManagedPolicyArns', []))
    assert attached == set(C4IAM.DEPLOY_ATTACHABLE_MANAGED_POLICIES)


def test_every_stack_and_generated_iam_name_is_in_the_deployable_namespace(synthesized_templates):
    for stack_name, template in synthesized_templates.values():
        assert stack_name.startswith('c4-'), stack_name
        for logical_id, resource in template['Resources'].items():
            if resource['Type'] in ('AWS::IAM::Role', 'AWS::IAM::User', 'AWS::IAM::InstanceProfile',
                                    'AWS::IAM::ManagedPolicy'):
                properties = resource['Properties']
                # CloudFormation generates the name, so it starts with the stack name.
                for explicit in ('RoleName', 'UserName', 'InstanceProfileName', 'ManagedPolicyName',
                                 'Path'):
                    assert explicit not in properties, (stack_name, logical_id, explicit)


def test_roles_passed_by_the_templates_go_only_to_the_permitted_services(synthesized_templates):
    trusted = set()
    for _, template in synthesized_templates.values():
        for logical_id, resource in template['Resources'].items():
            if resource['Type'] == 'AWS::IAM::Role' and 'DevRole' not in logical_id:
                for statement in resource['Properties']['AssumeRolePolicyDocument']['Statement']:
                    trusted |= set(_as_list(statement.get('Principal', {}).get('Service', [])))
    # Roles trusted by ecs.amazonaws.com / vpc-flow-logs / autoscaling exist in the IAM stack but
    # no template hands them to those services, so those are not passable.
    used = {'codebuild.amazonaws.com', 'ec2.amazonaws.com', 'ecs-tasks.amazonaws.com'}
    assert used <= trusted
    assert set(C4IAM.DEPLOY_PASS_ROLE_SERVICES) == used | {'lambda.amazonaws.com'}


# ---------------------------------------------------------------------------------------------
# 4b. The datastore KMS key policy (dual authorization for a new encrypted datastore)
# ---------------------------------------------------------------------------------------------

DEPLOY_ROLE_ARN = f'arn:aws:iam::{ACCOUNT}:role/c4-iam-main-stack-CGAPInfraDeployRole-1A2B3C4D5E6F7'
DEPLOYING_IAM_USER = f'arn:aws:iam::{ACCOUNT}:user/administrator'


def _datastore_template(**overrides) -> dict:
    """ The real datastore stack (encryption on, the default) under the CI config plus overrides. """
    config = dict(ConfigManager.singleton()._get_config(), **SYNTHESIS_EXTRAS,
                  **{Settings.DEPLOYING_IAM_USER: DEPLOYING_IAM_USER}, **overrides)
    config.pop(Settings.S3_BUCKET_ENCRYPTION, None)
    with _registered_stacks(), \
            mock.patch.object(ConfigManager.singleton(), '_CACHED_CONFIG', config), \
            mock.patch.object(ConfigManager, 'find_stack_output', return_value='offline-value'), \
            mock.patch.object(ApplicationConfigurationSecrets, 'get_es_url',
                              return_value='offline.example.invalid'):
        creator = base.REGISTERED_STACKS['alpha']['datastore']
        return creator(account=C4Account(account_number=ACCOUNT, creds_file='/dev/null')).template.to_dict()


def _key(template: dict) -> dict:
    [key] = [r['Properties'] for r in template['Resources'].values() if r['Type'] == 'AWS::KMS::Key']
    return key


def _key_policy_for(principal_arn: str, key: dict) -> list:
    """ Key-policy statements naming the principal, with the IAM-stack import resolved to it. """
    import_value = {'Fn::ImportValue': {'Fn::Sub': '${IAMStackNameParameter}-HumanDeployRoleArn'}}
    statements = []
    for statement in key['KeyPolicy']['Statement']:
        principals = [principal_arn if p == import_value else p
                      for p in _as_list(statement['Principal']['AWS'])]
        if principal_arn in principals:
            statements.append({k: v for k, v in statement.items() if k != 'Principal'})
    return statements


def _datastore_deploy_config():
    """ ENABLED_DEPLOY as config.json values (ConfigManager stringifies JSON values). """
    return {key: str(value).lower() if isinstance(value, bool) else value
            for key, value in ENABLED_DEPLOY.items()}


def test_datastore_key_policy_is_unchanged_unless_the_deploy_role_is_built():
    baseline = _key(_datastore_template())
    assert [s['Sid'] for s in baseline['KeyPolicy']['Statement']] == [
        'Enable Admin IAM Policies', 'Allow use of the key']
    # A flag without principals builds no role, so the key policy must not import one either.
    assert _key(_datastore_template(**{Settings.HUMAN_ACCESS_DEPLOY_ENABLED: 'true'})) == baseline
    assert _key(_datastore_template(**{Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS: DEPLOYERS})) == baseline


def test_datastore_key_policy_names_the_deploy_role_and_keeps_existing_principals():
    baseline = _key(_datastore_template())
    template = _datastore_template(**_datastore_deploy_config())
    key = _key(template)
    statements = key['KeyPolicy']['Statement']
    assert statements[:2] == baseline['KeyPolicy']['Statement']  # deploying_iam_user etc. untouched
    assert statements[0]['Principal'] == {'AWS': [DEPLOYING_IAM_USER]} and statements[0]['Action'] == 'kms:*'
    assert len(statements) == 4
    # The import resolves to the export the IAM stack creates for the role.
    assert 'IAMStackNameParameter' in template['Parameters']
    iam_export = _deploy_template()['Outputs']['C4IAMMainHumanDeployRoleArn']['Export']['Name']['Fn::Sub']
    for statement in statements[2:]:
        assert statement['Principal']['AWS'] == [
            {'Fn::ImportValue': {'Fn::Sub': iam_export.replace('AWS::StackName', 'IAMStackNameParameter')}}]
    # No lockout bypass: KMS's safety check stays in force for every caller.
    assert 'BypassPolicyLockoutSafetyCheck' not in key


def test_new_datastore_key_is_creatable_and_maintainable_by_the_deploy_role():
    """ Every AWS::KMS::Key handler action the role is meant to perform must be allowed by BOTH its
        IAM policy and the generated key policy. PutKeyPolicy is what KMS's CreateKey lockout check
        requires the creating principal to hold under the new policy.
    """
    key_statements = _key_policy_for(DEPLOY_ROLE_ARN, _key(_datastore_template(**_datastore_deploy_config())))
    key_arn = f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd'
    handlers = REFERENCE['handler_permissions']['AWS::KMS::Key']
    needed = {a for operation in ('create', 'read', 'update') for a in handlers[operation]
              if not _not_granted_reason(a)}
    assert 'kms:PutKeyPolicy' in needed and 'kms:CreateKey' in needed
    for action in sorted(needed - {'kms:CreateKey'}):  # CreateKey is IAM-only: no key exists yet
        assert _decide(action, key_arn, statements=key_statements) == 'allow', f'key policy: {action}'
        assert _decide(action, key_arn) == 'allow', f'IAM: {action}'
    assert _decide('kms:CreateKey', '*') == 'allow'
    via_s3 = {'kms:ViaService': f's3.{REGION}.amazonaws.com'}
    for action in ('kms:GenerateDataKey', 'kms:Decrypt'):
        assert _decide(action, key_arn, via_s3, statements=key_statements) == 'allow'
        assert _decide(action, key_arn, via_s3) == 'allow'
        assert _decide(action, key_arn, statements=key_statements) == 'implicit-deny'


@pytest.mark.parametrize('action', ['kms:ScheduleKeyDeletion', 'kms:DisableKey', 'kms:CreateGrant',
                                    'kms:Encrypt', 'kms:ReEncryptFrom', 'kms:ReplicateKey',
                                    'kms:ImportKeyMaterial', 'kms:CancelKeyDeletion'])
def test_key_policy_grants_the_deploy_role_no_key_administration_beyond_deployment(action):
    key_statements = _key_policy_for(DEPLOY_ROLE_ARN, _key(_datastore_template(**_datastore_deploy_config())))
    assert _decide(action, f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd',
                   {'kms:ViaService': f's3.{REGION}.amazonaws.com'}, statements=key_statements) != 'allow'


# ---------------------------------------------------------------------------------------------
# 5. Scenarios: what the role can and cannot do
# ---------------------------------------------------------------------------------------------

def _cfn(stack):
    return f'arn:aws:cloudformation:{REGION}:{ACCOUNT}:stack/{stack}/0a1b2c3d'


def _iam(suffix):
    return f'arn:aws:iam::{ACCOUNT}:{suffix}'


ECS_ROLE = _iam('role/' + _generated_name('c4-iam-main-stack', 'CGAPECSRole'))
CODEBUILD_ROLE = _iam('role/' + _generated_name('c4-codebuild-cgap-build-stack', 'CodeBuildRoleForCgapBuild'))
FOURSIGHT_ROLE = _iam('role/' + _generated_name('c4-foursight-cgap-build-stack', 'DefaultRole'))
PROTECTED_ROLES = [_iam('role/' + _generated_name('c4-iam-main-stack', logical_id)) for logical_id in (
    'CGAPDevDiagnoseRole', 'SMaHTPowerRemediateRole', 'FFInfraDeployRole', 'CGAPDevRole')]
PROTECTED_POLICIES = [_iam('policy/' + _generated_name('c4-iam-main-stack', logical_id)) for logical_id in (
    'C4IAMMainHumanAccessBoundary', 'C4IAMMainInfraDeployStackPolicy')]


@pytest.mark.parametrize('action, resource, context', [
    ('cloudformation:CreateChangeSet', _cfn('c4-ecs-cgap-build-stack'), {}),
    ('cloudformation:CreateChangeSet',
     f'arn:aws:cloudformation:{REGION}:aws:transform/Serverless-2016-10-31', {}),
    ('cloudformation:ExecuteChangeSet', _cfn('c4-datastore-cgap-build-stack'), {}),
    ('cloudformation:ContinueUpdateRollback', _cfn('c4-network-main-stack'), {}),
    ('cloudformation:RollbackStack', _cfn('c4-ecs-cgap-build-stack'), {}),
    ('cloudformation:DeleteStack', _cfn('c4-ecs-cgap-build-stack'), {}),
    ('cloudformation:CancelUpdateStack', _cfn('c4-datastore-cgap-build-stack'), {}),
    ('cloudformation:DescribeStacks', '*', {}),
    # Image builds: CodeBuild projects are named after the environment, not c4-*.
    ('codebuild:StartBuild', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build', {}),
    ('codebuild:StartBuild', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build-tibanna-awsf-builder', {}),
    ('codebuild:StopBuild', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build-blue', {}),
    ('codebuild:BatchGetBuilds', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build', {}),
    ('codebuild:ListBuildsForProject', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build', {}),
    ('codebuild:ListProjects', '*', {}),
    # Image push (registry login, then docker push) to the portal and Tibanna repositories.
    ('ecr:GetAuthorizationToken', '*', {}),
    ('ecr:BatchCheckLayerAvailability', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/cgap-build', {}),
    ('ecr:InitiateLayerUpload', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/tibanna-awsf', {}),
    ('ecr:UploadLayerPart', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/tibanna-awsf', {}),
    ('ecr:CompleteLayerUpload', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/tibanna-awsf', {}),
    ('ecr:PutImage', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/cgap-build', {}),
    ('ecr:BatchGetImage', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/cgap-build', {}),
    ('iam:CreateRole', ECS_ROLE, {}),
    ('iam:PutRolePolicy', FOURSIGHT_ROLE, {}),
    ('iam:DeleteRole', CODEBUILD_ROLE, {}),
    ('iam:AttachRolePolicy', CODEBUILD_ROLE,
     {'iam:PolicyARN': 'arn:aws:iam::aws:policy/AmazonS3FullAccess'}),
    ('iam:PassRole', ECS_ROLE, {'iam:PassedToService': 'ecs-tasks.amazonaws.com'}),
    ('iam:PassRole', FOURSIGHT_ROLE, {'iam:PassedToService': 'lambda.amazonaws.com'}),
    ('iam:PassRole', ECS_ROLE, {}),  # e.g. AddRoleToInstanceProfile: no service in context
    ('iam:CreateServiceLinkedRole', _iam('role/aws-service-role/es.amazonaws.com/x'),
     {'iam:AWSServiceName': 'es.amazonaws.com'}),
    ('ecs:RegisterTaskDefinition', '*', {}),
    ('ecs:UpdateService', f'arn:aws:ecs:{REGION}:{ACCOUNT}:service/c4-ecs/portal', {}),
    ('rds:ModifyDBInstance', f'arn:aws:rds:{REGION}:{ACCOUNT}:db:rds-cgap-build', {}),
    ('es:UpdateDomainConfig', f'arn:aws:es:{REGION}:{ACCOUNT}:domain/os-cgap-build', {}),
    ('lambda:UpdateFunctionCode', f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:c4-foursight-x', {}),
    ('lambda:GetLayerVersion', f'arn:aws:lambda:{REGION}:865557043974:layer:git-lambda-al2023:1', {}),
    ('s3:PutObject', 'arn:aws:s3:::cgap-build-foursight-application-versions/deployment.zip',
     {'s3:ResourceAccount': ACCOUNT}),
    ('s3:PutBucketPolicy', 'arn:aws:s3:::cgap-build-application-files', {}),
    ('kms:GenerateDataKey', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd',
     {'kms:ViaService': f's3.{REGION}.amazonaws.com'}),
    ('kms:CreateKey', '*', {}),
    ('kms:PutKeyPolicy', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd', {}),
    ('secretsmanager:CreateSecret', f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4AppConfigCgapBuild-a1', {}),
    ('secretsmanager:PutSecretValue',
     f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4DatastoreCgapBuildRDSSecret-a1', {}),
    ('secretsmanager:GetSecretValue',
     f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4DatastoreCgapBuildRDSSecret-a1', {}),
])
def test_deployment_operations_are_allowed(action, resource, context):
    assert _decide(action, resource, context) == 'allow'


@pytest.mark.parametrize('action, resource, context, expected', [
    # Only reviewed change sets for c4-* stacks; no service role; no deletion; home region only.
    ('cloudformation:CreateChangeSet', _cfn('c4-ecs-cgap-build-stack'),
     {'cloudformation:RoleArn': _iam('role/c4-x')}, 'implicit-deny'),
    ('cloudformation:CreateChangeSet', _cfn('someone-elses-stack'), {}, 'implicit-deny'),
    ('cloudformation:CreateChangeSet', _cfn('c4-ecs-cgap-build-stack'),
     {'aws:RequestedRegion': 'us-west-2'}, 'deny'),
    ('cloudformation:CreateStack', _cfn('c4-ecs-cgap-build-stack'), {}, 'implicit-deny'),
    ('cloudformation:UpdateStack', _cfn('c4-ecs-cgap-build-stack'), {}, 'implicit-deny'),
    # Stack deletion/rollback: c4-* stacks only, home region only, never via a service role,
    # and no removal of administrator-set protections.
    ('cloudformation:DeleteStack', _cfn('someone-elses-stack'), {}, 'deny'),
    ('cloudformation:RollbackStack', _cfn('StackSet-landing-zone-baseline'), {}, 'deny'),
    ('cloudformation:DeleteStack', _cfn('c4-ecs-cgap-build-stack'),
     {'cloudformation:RoleArn': _iam('role/c4-x')}, 'implicit-deny'),
    ('cloudformation:ContinueUpdateRollback', _cfn('c4-ecs-cgap-build-stack'),
     {'cloudformation:RoleArn': _iam('role/c4-x')}, 'implicit-deny'),
    ('cloudformation:DeleteStack', _cfn('c4-ecs-cgap-build-stack'),
     {'aws:RequestedRegion': 'us-west-2'}, 'deny'),
    ('cloudformation:DeleteStackSet', '*', {}, 'deny'),
    ('cloudformation:UpdateTerminationProtection', _cfn('c4-datastore-cgap-build-stack'), {}, 'deny'),
    ('cloudformation:SetStackPolicy', _cfn('c4-datastore-cgap-build-stack'), {}, 'deny'),
    # IAM outside the generated namespace, or on the protected identities.
    ('iam:CreateRole', _iam('role/Admin'), {}, 'implicit-deny'),
    ('iam:PutRolePolicy', _iam('role/OrganizationAccountAccessRole'), {}, 'implicit-deny'),
    ('iam:AttachRolePolicy', CODEBUILD_ROLE,
     {'iam:PolicyARN': 'arn:aws:iam::aws:policy/AdministratorAccess'}, 'implicit-deny'),
    ('iam:PassRole', ECS_ROLE, {'iam:PassedToService': 'cloudformation.amazonaws.com'}, 'implicit-deny'),
    ('iam:PassRole', _iam('role/Admin'), {'iam:PassedToService': 'ec2.amazonaws.com'}, 'implicit-deny'),
    ('iam:CreateServiceLinkedRole', _iam('role/aws-service-role/x'),
     {'iam:AWSServiceName': 'support.amazonaws.com'}, 'implicit-deny'),
    ('iam:CreateAccessKey', _iam('user/c4-iam-main-stack-S3Federator-X'), {}, 'deny'),
    ('iam:CreateUser', _iam('user/mallory'), {}, 'implicit-deny'),
    ('iam:CreatePolicy', _iam('policy/c4-anything'), {}, 'deny'),
    ('sts:AssumeRole', ECS_ROLE, {}, 'deny'),
    ('sts:GetFederationToken', '*', {}, 'deny'),
    ('organizations:LeaveOrganization', '*', {}, 'deny'),
    # Runtime/workload execution is not deployment.
    ('lambda:InvokeFunction', f'arn:aws:lambda:{REGION}:{ACCOUNT}:function:c4-foursight-x', {}, 'deny'),
    ('ecs:RunTask', '*', {}, 'deny'),
    ('ecs:ExecuteCommand', '*', {}, 'deny'),
    ('codebuild:RetryBuild', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build', {}, 'deny'),
    ('codebuild:StartBuildBatch', f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/cgap-build', {}, 'deny'),
    ('codebuild:StartBuild', f'arn:aws:codebuild:{REGION}:{OTHER_ACCOUNT}:project/cgap-build', {},
     'implicit-deny'),
    ('codebuild:StartBuild', f'arn:aws:codebuild:us-west-2:{ACCOUNT}:project/cgap-build',
     {'aws:RequestedRegion': 'us-west-2'}, 'deny'),
    ('ssm:StartSession', '*', {}, 'deny'),
    # Images can be pushed and retagged in this account's repositories, never deleted.
    ('ecr:BatchDeleteImage', f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/cgap-build', {}, 'deny'),
    ('ecr:PutImage', f'arn:aws:ecr:{REGION}:{OTHER_ACCOUNT}:repository/cgap-build', {}, 'implicit-deny'),
    ('ecr:SetRepositoryPolicy', f'arn:aws:ecr:{REGION}:{OTHER_ACCOUNT}:repository/cgap-build', {},
     'implicit-deny'),
    ('es:ESHttpPost', f'arn:aws:es:{REGION}:{ACCOUNT}:domain/os-cgap-build/*', {}, 'deny'),
    # Data-bearing teardown.
    ('rds:DeleteDBInstance', f'arn:aws:rds:{REGION}:{ACCOUNT}:db:rds-cgap-build', {}, 'deny'),
    ('es:DeleteDomain', f'arn:aws:es:{REGION}:{ACCOUNT}:domain/os-cgap-build', {}, 'deny'),
    ('s3:DeleteBucket', 'arn:aws:s3:::cgap-build-application-files', {}, 'deny'),
    ('s3:DeleteObject', 'arn:aws:s3:::cgap-build-foursight-application-versions/x', {}, 'deny'),
    ('sqs:PurgeQueue', f'arn:aws:sqs:{REGION}:{ACCOUNT}:cgap-build-indexer-queue', {}, 'deny'),
    ('kms:ScheduleKeyDeletion', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd', {}, 'deny'),
    ('secretsmanager:DeleteSecret', '*', {}, 'deny'),
    ('logs:DeleteLogGroup', '*', {}, 'deny'),
    # Data plane outside the package bucket, other accounts, and direct key use.
    ('s3:GetObject', 'arn:aws:s3:::cgap-build-application-files/private.bam',
     {'s3:ResourceAccount': ACCOUNT}, 'implicit-deny'),
    ('s3:PutObject', 'arn:aws:s3:::cgap-build-foursight-application-versions/x',
     {'s3:ResourceAccount': OTHER_ACCOUNT}, 'implicit-deny'),
    ('kms:Decrypt', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd', {}, 'implicit-deny'),
    ('sqs:ReceiveMessage', f'arn:aws:sqs:{REGION}:{ACCOUNT}:q', {}, 'deny'),
    # Filled application configuration cannot be overwritten by an ordinary deployment.
    ('secretsmanager:PutSecretValue',
     f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4AppConfigCgapBuild-a1', {}, 'deny'),
    ('secretsmanager:UpdateSecret',
     f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4AppConfigCgapBuild-a1', {}, 'deny'),
    ('secretsmanager:UpdateSecret',
     f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4DatastoreCgapBuildRDSSecret-a1', {}, 'deny'),
    ('secretsmanager:PutResourcePolicy', '*', {}, 'deny'),
])
def test_non_deployment_operations_are_refused(action, resource, context, expected):
    assert _decide(action, resource, context) == expected


@pytest.mark.parametrize('resource', PROTECTED_ROLES + PROTECTED_POLICIES)
@pytest.mark.parametrize('action', ['iam:PutRolePolicy', 'iam:AttachRolePolicy', 'iam:UpdateAssumeRolePolicy',
                                    'iam:DeleteRole', 'iam:PassRole', 'iam:CreatePolicyVersion',
                                    'iam:TagRole', 'iam:DeleteRolePermissionsBoundary'])
def test_role_cannot_modify_or_pass_itself_or_the_other_human_access_identities(action, resource):
    assert _decide(action, resource, {'iam:PassedToService': 'lambda.amazonaws.com',
                                      'iam:PolicyARN': 'arn:aws:iam::aws:policy/AmazonS3FullAccess'}) == 'deny'


@pytest.mark.parametrize('resource', [ECS_ROLE, CODEBUILD_ROLE, FOURSIGHT_ROLE])
def test_runtime_role_names_are_not_caught_by_the_protection_patterns(resource):
    assert _decide('iam:PutRolePolicy', resource) == 'allow'


# ---------------------------------------------------------------------------------------------
# 6. Credential path: what the supported commands actually call, with role-shaped credentials
# ---------------------------------------------------------------------------------------------

ROLE_SESSION_ENV = {
    'AWS_ACCESS_KEY_ID': 'ASIAOFFLINEEXAMPLE00',  # ASIA = temporary (STS) credentials
    'AWS_SECRET_ACCESS_KEY': 'offline-secret',
    'AWS_SESSION_TOKEN': 'offline-session-token',
    'AWS_DEFAULT_REGION': REGION,
}


def test_synthesis_keeps_the_assumed_role_session_from_the_environment():
    """ `cli provision <stack>` (no --upload-change-set) synthesizes in-process. Sourcing the
        configuration must not replace or hide the session's environment credentials.
    """
    with mock.patch.dict(os.environ, ROLE_SESSION_ENV), \
            mock.patch.dict(os.environ, {'AWS_SHARED_CREDENTIALS_FILE': '/dev/null',
                                         'AWS_CONFIG_FILE': '/dev/null'}):
        with ConfigManager.validate_and_source_configuration():
            credentials = botocore.session.get_session().get_credentials()
            assert credentials.method == 'env'
            assert credentials.access_key == ROLE_SESSION_ENV['AWS_ACCESS_KEY_ID']
            assert credentials.token == ROLE_SESSION_ENV['AWS_SESSION_TOKEN']


def test_upload_change_set_runs_docker_with_only_the_custom_credentials_directory(tmp_path):
    """ Documents why the deployment workflow does not use --upload-change-set/--validate: those
        run amazon/aws-cli in Docker with custom/aws_creds mounted and no environment forwarded,
        so an assumed-role session in the operator's shell is never used.
    """
    class Stack:
        class name:
            stack_name = 'c4-ecs-cgap-build-stack'
    with _registered_stacks() as cli, mock.patch.dict(os.environ, ROLE_SESSION_ENV), \
            mock.patch('os.system') as system:
        cli.C4Client.upload_cloudformation_template(stack=Stack, file_path='/root/out/templates/x.yaml')
    command = system.call_args[0][0]
    assert 'docker run' in command and ':/root/.aws' in command
    assert ' -e ' not in command and 'AWS_SESSION_TOKEN' not in command


def _stubbed(service, region=REGION):
    session = botocore.session.get_session()
    with mock.patch.dict(os.environ, ROLE_SESSION_ENV):
        client = session.create_client(service, region_name=region)
    return client, Stubber(client)


def test_aws_cli_deploy_api_calls_are_all_allowed():
    """ Drives the AWS CLI's own change-set code (awscli.customizations.cloudformation.deployer)
        and checks every API it calls against the policy for a c4-* stack.
    """
    from awscli.customizations.cloudformation.deployer import Deployer
    client, stubber = _stubbed('cloudformation')
    stack_id = _cfn('c4-ecs-cgap-build-stack')
    stubber.add_response('describe_stacks', {'Stacks': [{
        'StackName': 'c4-ecs-cgap-build-stack', 'StackId': stack_id, 'StackStatus': 'UPDATE_COMPLETE',
        'CreationTime': '2026-01-01T00:00:00Z'}]})
    stubber.add_response('get_template_summary', {'Parameters': []})
    stubber.add_response('create_change_set', {'Id': f'arn:aws:cloudformation:{REGION}:{ACCOUNT}'
                                                     f':changeSet/c/1', 'StackId': stack_id})
    stubber.add_response('describe_change_set', {'Status': 'CREATE_COMPLETE', 'Changes': []})
    with stubber:
        Deployer(client).create_and_wait_for_changeset(
            stack_name='c4-ecs-cgap-build-stack', cfn_template='{}', parameter_values=[],
            capabilities=['CAPABILITY_IAM'], role_arn=None, notification_arns=None,
            s3_uploader=None, tags=[])
    stubber.assert_no_pending_responses()  # exactly these four API calls were made, in order
    for operation in ('DescribeStacks', 'GetTemplateSummary', 'CreateChangeSet', 'DescribeChangeSet',
                      'ExecuteChangeSet'):
        resource = '*' if operation in ('DescribeStacks', 'GetTemplateSummary', 'DescribeChangeSet') else stack_id
        assert _decide(f'cloudformation:{operation}', resource) == 'allow', operation


def test_aws_cli_package_upload_with_kms_is_allowed():
    """ `aws cloudformation package/deploy --s3-bucket ... --kms-key-id ...` upload path. """
    from awscli.customizations.s3uploader import S3Uploader
    client, stubber = _stubbed('s3')
    bucket = 'cgap-build-foursight-application-versions'
    uploader = S3Uploader(client, bucket, prefix=None, kms_key_id='abcd-key')
    # The dedup check is a HeadObject (authorized as s3:GetObject); any error means "upload it".
    stubber.add_client_error('head_object', service_error_code='403', http_status_code=403,
                             expected_params={'Bucket': bucket, 'Key': 'deployment.zip'})
    with stubber:
        assert uploader.file_exists('deployment.zip') is False
    stubber.assert_no_pending_responses()
    assert uploader.kms_key_id == 'abcd-key'  # uploads then request SSE-KMS with this key
    assert _decide('s3:PutObject', f'arn:aws:s3:::{bucket}/deployment.zip',
                   {'s3:ResourceAccount': ACCOUNT}) == 'allow'
    assert _decide('s3:GetObject', f'arn:aws:s3:::{bucket}/deployment.zip',
                   {'s3:ResourceAccount': ACCOUNT}) == 'allow'
    assert _decide('kms:GenerateDataKey', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/abcd-key',
                   {'kms:ViaService': f's3.{REGION}.amazonaws.com'}) == 'allow'


def _recording_client(service, responses: dict, boto3_session=False):
    """ A real botocore (or boto3, for its S3 transfer methods) client whose calls are answered
        locally, before any request is signed or sent. `calls` records each operation name with the
        API parameters the command passed, so a command's actual calls can be checked.
    """
    with mock.patch.dict(os.environ, ROLE_SESSION_ENV):
        if boto3_session:
            import boto3
            client = boto3.session.Session().client(service, region_name=REGION)
        else:
            client = botocore.session.get_session().create_client(service, region_name=REGION)
    calls = []

    def remember(params, context, **_):
        context['offline_api_params'] = dict(params)

    def answer(model, context, **_):
        api_params = context.get('offline_api_params', {})
        calls.append((model.name, api_params))
        return mock.Mock(status_code=200, headers={}), responses[model.name](api_params)
    client.meta.events.register(f'before-parameter-build.{service}', remember)
    client.meta.events.register(f'before-call.{service}', answer)
    return client, calls


def _names(calls):
    return [name for name, _ in calls]


ECR_REPO_ARN = f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/cgap-build'
NEW_DIGEST = 'sha256:' + 'a' * 64
OLD_DIGEST = 'sha256:' + 'b' * 64


def _image(digest, tags, day):
    return {'imageDigest': digest, 'imageTags': tags, 'imagePushedAt': f'2026-11-0{day}T00:00:00Z'}


def test_add_image_tag_and_unrelease_api_calls_are_all_allowed():
    """ Drives dcicutils' add-image-tag / unrelease-most-recent-image (pyproject scripts) and
        checks every ECR API they call for this account's repository.
    """
    from dcicutils.ecr_scripts import ECRCommandContext
    images = [_image(NEW_DIGEST, ['released', 'latest'], 2), _image(OLD_DIGEST, ['v1'], 1)]
    client, calls = _recording_client('ecr', {
        'DescribeImages': lambda params: {'imageDetails': [
            i for i in images if 'imageIds' not in params or any(
                ids.get('imageDigest') == i['imageDigest'] or ids.get('imageTag') in i['imageTags']
                for ids in params['imageIds'])]},
        'BatchGetImage': lambda params: {'images': [{'imageManifest': '{"schemaVersion": 2}'}]},
        'PutImage': lambda params: {'image': {'imageId': {'imageTag': params['imageTag']}}},
    })
    context = ECRCommandContext(account_number=ACCOUNT, image_repository='cgap-build', ecr_client=client)
    with mock.patch('dcicutils.ecr_scripts.PRINT'):
        context.add_image_tag(digest=OLD_DIGEST, tag='v1-hotfix')
        context.unrelease_most_recent_image()  # moves 'released' via the same add_image_tag
    assert set(_names(calls)) == {'DescribeImages', 'BatchGetImage', 'PutImage'}
    for operation in set(_names(calls)):
        assert _decide(f'ecr:{operation}', ECR_REPO_ARN) == 'allow', operation


def test_documented_image_push_permissions_are_all_allowed():
    """ `aws ecr get-login-password | docker login` then `docker push` (scripts/upload_tibanna_awsf,
        portal Makefile, CodeBuild-less builds). The action list is AWS's documented push set
        (Amazon ECR User Guide, "IAM permissions for pushing an image").
    """
    assert _decide('ecr:GetAuthorizationToken', '*') == 'allow'
    for action in ('ecr:BatchCheckLayerAvailability', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
                   'ecr:CompleteLayerUpload', 'ecr:PutImage', 'ecr:BatchGetImage'):
        for repository in ('cgap-build', 'tibanna-awsf'):
            arn = f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{repository}'
            assert _decide(action, arn) == 'allow', (action, repository)


def test_build_project_names_generated_by_the_codebuild_stack_can_be_started(synthesized_templates):
    projects = [resource['Properties']['Name'] for _, template in synthesized_templates.values()
                for resource in template['Resources'].values()
                if resource['Type'] == 'AWS::CodeBuild::Project']
    assert projects
    for name in projects:
        arn = f'arn:aws:codebuild:{REGION}:{ACCOUNT}:project/{name}'
        for action in ('codebuild:StartBuild', 'codebuild:StopBuild', 'codebuild:BatchGetBuilds'):
            assert _decide(action, arn) == 'allow', (action, name)
        assert _decide('codebuild:RetryBuild', arn) == 'deny'


def test_failed_stack_cleanup_sequence_is_allowed_for_c4_stacks():
    """ The AWS CLI recovery path for a failed stack: continue or force the rollback, delete,
        wait, and - when data-bearing resources fail to delete - delete again retaining them.
    """
    stack = 'c4-datastore-cgap-build-stack'
    stack_id = _cfn(stack)
    status = iter(['DELETE_FAILED', 'DELETE_COMPLETE'])
    client, calls = _recording_client('cloudformation', {
        'ContinueUpdateRollback': lambda params: {},
        'RollbackStack': lambda params: {'StackId': stack_id},
        'DeleteStack': lambda params: {},
        'DescribeStacks': lambda params: {'Stacks': [{
            'StackName': stack, 'StackId': stack_id, 'StackStatus': next(status),
            'CreationTime': '2026-01-01T00:00:00Z'}]},
    })
    client.continue_update_rollback(StackName=stack)
    client.rollback_stack(StackName=stack)
    client.delete_stack(StackName=stack)
    assert client.describe_stacks(StackName=stack)['Stacks'][0]['StackStatus'] == 'DELETE_FAILED'
    client.delete_stack(StackName=stack, RetainResources=['RDS', 'ApplicationFilesBucket'])
    assert client.describe_stacks(StackName=stack)['Stacks'][0]['StackStatus'] == 'DELETE_COMPLETE'
    for operation in _names(calls):
        resource = '*' if operation == 'DescribeStacks' else stack_id
        assert _decide(f'cloudformation:{operation}', resource) == 'allow', operation


# Resource types whose CloudFormation delete handler needs an action the guardrail denies: a stack
# deletion (or a change set removing/replacing them) leaves them in place, retained.
RETAINED_ON_DELETE = {
    'AWS::RDS::DBInstance', 'AWS::OpenSearchService::Domain', 'AWS::S3::Bucket',
    'AWS::SQS::Queue', 'AWS::SecretsManager::Secret', 'AWS::KMS::Key', 'AWS::ECR::Repository',
    'AWS::Logs::LogGroup', 'AWS::ElastiCache::ReplicationGroup',
    # The S3 federator user: removing its access key or login profile is credential
    # administration, which this role does not have.
    'AWS::IAM::User',
}


def test_stack_deletion_can_remove_everything_except_the_data_bearing_resources(synthesized_templates):
    """ What DeleteStack can and cannot clean up, from AWS's own delete-handler permissions:
        everything except the data-bearing types, which fail to delete and must be retained
        (and then removed, if at all, by an administrator).
    """
    statements = _deploy_statements()
    types = _template_resource_types(synthesized_templates) | FOURSIGHT_RESOURCE_TYPES
    retained = set()
    for resource_type in types:
        handlers = REFERENCE['handler_permissions'][resource_type]
        if handlers is None:
            continue  # legacy AWS::Elasticsearch::Domain: es:DeleteElasticsearchDomain is denied
        blocked = [a for a in handlers.get('delete', [])
                   if _not_granted_reason(a) not in (UNUSED, INVALID)
                   and not _allowed_somewhere(a, statements)]
        if blocked:
            retained.add(resource_type)
    assert retained == RETAINED_ON_DELETE & types
    assert _decide('es:DeleteElasticsearchDomain', f'arn:aws:es:{REGION}:{ACCOUNT}:domain/x') == 'deny'


# ECS release commands: deploy-ecs and identity-swap, driven through locally answered clients.

def _ecs_cluster(name):
    return f'arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/{name}'


def _ecs_service(cluster, name):
    return f'arn:aws:ecs:{REGION}:{ACCOUNT}:service/{cluster}/{name}'


def _request_decisions(service, calls):
    """ (IAM action, resource, context) for each recorded call, then the policy's decision. """
    decisions = []
    for operation, params in calls:
        context = {}
        if service == 'ecs':
            action = f'ecs:{operation}'
            targets = (params.get('services') or [params['service']]
                       if operation in ('DescribeServices', 'UpdateService') else ['*'])
        elif service == 'application-autoscaling':
            action = f'application-autoscaling:{operation}'
            if operation.startswith('Describe'):
                targets = ['*']
            else:
                targets = [f'arn:aws:application-autoscaling:{REGION}:{ACCOUNT}:scalable-target/0123abcd']
                context = {'application-autoscaling:service-namespace': params['ServiceNamespace'],
                           'application-autoscaling:scalable-dimension': params['ScalableDimension']}
        elif service == 'cloudwatch':
            action = f'cloudwatch:{operation}'
            name = params.get('AlarmName') or params['AlarmNames'][0]
            targets = [f'arn:aws:cloudwatch:{REGION}:{ACCOUNT}:alarm:{name}']
        elif service == 's3':
            action = {'HeadObject': 's3:GetObject'}.get(operation, f's3:{operation}')
            targets = [f'arn:aws:s3:::{params["Bucket"]}/{params["Key"]}']
            context = {'s3:ResourceAccount': ACCOUNT}
        else:
            raise AssertionError(service)
        for target in targets:
            decisions.append((action, target, _decide(action, target, context)))
    return decisions


def _ecs_responses(clusters, services_by_cluster, task_by_service, task_definitions=()):
    return {
        'ListClusters': lambda params: {'clusterArns': clusters},
        'ListServices': lambda params: {'serviceArns': services_by_cluster[params['cluster']]},
        'ListTaskDefinitions': lambda params: {'taskDefinitionArns': list(task_definitions)},
        'DescribeServices': lambda params: {'services': [
            {'serviceArn': arn, 'taskDefinition': task_by_service[arn]} for arn in params['services']],
            'failures': []},
        'UpdateService': lambda params: {'service': {'serviceArn': params['service']}},
    }


def test_deploy_ecs_api_calls_are_all_allowed():
    """ `deploy-ecs --list` and `deploy-ecs --kick --env <cluster>` (src/commands/deploy_ecs.py). """
    from src.commands import deploy_ecs
    cluster = _ecs_cluster('c4-ecs-cgap-build-stack-CGAPDockerClusterBuild-AbC')
    services = [_ecs_service(cluster.split('/')[-1], name) for name in ('Portal', 'Indexer', 'Ingester')]
    client, calls = _recording_client('ecs', _ecs_responses([cluster], {cluster: services}, {}))
    assert deploy_ecs.list_clusters(client) == [cluster]
    deploy_ecs.kick_cluster_update(client, cluster)
    assert _names(calls) == ['ListClusters', 'ListServices'] + ['UpdateService'] * 3
    assert all(params['forceNewDeployment'] for name, params in calls if name == 'UpdateService')
    denied = [d for d in _request_decisions('ecs', calls) if d[2] != 'allow']
    assert not denied, denied


@pytest.mark.parametrize('argv, expected_calls', [
    (['--list'], ['ListClusters']),
    (['--kick', '--env', 'CLUSTER'], ['ListServices', 'UpdateService']),
])
def test_deploy_ecs_command_runs_with_its_region_and_existing_interface(argv, expected_calls):
    """ Regression: deploy_ecs imported CGAP_ECS_REGION, which the locked dcicutils (8.19.0) no
        longer defines, so the command failed at import before making any call. It now takes the
        region from ECSUtils.REGION (us-east-1, unchanged). Flags, output and exit codes are as before.
    """
    from dcicutils.ecs_utils import ECSUtils
    from src.commands import deploy_ecs
    cluster = _ecs_cluster('c4-ecs-cgap-build-stack-CGAPDockerClusterBuild-AbC')
    services = [_ecs_service(cluster.split('/')[-1], 'Portal')]
    client, calls = _recording_client('ecs', _ecs_responses([cluster], {cluster: services}, {}))
    argv = [cluster if arg == 'CLUSTER' else arg for arg in argv]
    with mock.patch.object(deploy_ecs.boto3, 'client', return_value=client) as make_client, \
            mock.patch.object(sys, 'argv', ['deploy-ecs'] + argv), \
            mock.patch.object(deploy_ecs, 'PRINT') as printed:
        try:
            deploy_ecs.main()
        except SystemExit as exit_:
            assert exit_.code == 0
    make_client.assert_called_once_with('ecs', region_name=ECSUtils.REGION)
    assert ECSUtils.REGION == 'us-east-1'
    assert _names(calls) == expected_calls
    if argv == ['--list']:
        printed.assert_called_once_with([cluster])
    assert all(d[2] == 'allow' for d in _request_decisions('ecs', calls))


SMAHT_BLUE = 'c4-ecs-blue-green-smaht-production-stack-SmahtProductionBlue-AbC'
SMAHT_GREEN = 'c4-ecs-blue-green-smaht-production-stack-SmahtProductionGreen-DeF'


def _smaht_ecs():
    services, tasks = {}, {}
    for cluster, color in ((SMAHT_BLUE, 'blue'), (SMAHT_GREEN, 'green')):
        arns = [_ecs_service(cluster, f'{kind}Servicesmaht{color}-1') for kind in ('Portal', 'Indexer', 'Ingester')]
        services[_ecs_cluster(cluster)] = arns
        for arn in arns:
            kind = C4IdentitySwap._determine_service_type(arn)
            tasks[arn] = f'arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/Smaht{color}{kind}Task:7'
    return _ecs_responses(list(services), services, tasks)


def _s3_object(data: dict):
    from botocore.response import StreamingBody
    body = json.dumps(data).encode()
    return {'Body': StreamingBody(io.BytesIO(body), len(body)), 'ContentLength': len(body),
            'ETag': '"e"'}


def _s3_responses(files: dict):
    return {
        'HeadObject': lambda params: {'ContentLength': len(json.dumps(files[params['Key']])), 'ETag': '"e"'},
        'GetObject': lambda params: _s3_object(files[params['Key']]),
        'PutObject': lambda params: {'ETag': '"f"'},
    }


def _drive_identity_swap(swap, ecs_responses, s3_files, **kwargs):
    from src.commands import identity_swap
    ecs_client, ecs_calls = _recording_client('ecs', ecs_responses)
    autoscaling, autoscaling_calls = _recording_client('application-autoscaling', {
        'RegisterScalableTarget': lambda params: {},
        'DescribeScalingPolicies': lambda params: {'ScalingPolicies': [{'PolicyName': 'OldIndexerPolicy'}]},
        'DeleteScalingPolicy': lambda params: {},
        'PutScalingPolicy': lambda params: {
            'PolicyARN': f'arn:aws:autoscaling:{REGION}:{ACCOUNT}:scalingPolicy:1:resource/ecs/x:policyName/p'},
    })
    cloudwatch, cloudwatch_calls = _recording_client('cloudwatch', {
        'DescribeAlarms': lambda params: {'MetricAlarms': [{
            'MetricName': 'ApproximateNumberOfMessagesVisible', 'Namespace': 'AWS/SQS', 'Statistic': 'Average',
            'Period': 60, 'EvaluationPeriods': 1, 'Threshold': 1.0, 'Dimensions': []}]},
        'PutMetricAlarm': lambda params: {},
    })
    s3, s3_calls = _recording_client('s3', _s3_responses(s3_files), boto3_session=True)
    clients = {'application-autoscaling': autoscaling, 'cloudwatch': cloudwatch, 's3': s3}
    ecs_utils = mock.Mock(client=ecs_client)
    ecs_utils.list_ecs_clusters.side_effect = lambda: ecs_client.list_clusters()['clusterArns']
    ecs_utils.list_ecs_services.side_effect = (
        lambda cluster_name: ecs_client.list_services(cluster=cluster_name)['serviceArns'])
    ecs_utils.list_ecs_tasks.side_effect = (
        lambda: ecs_client.list_task_definitions()['taskDefinitionArns'])
    with mock.patch.object(identity_swap, 'ECSUtils', return_value=ecs_utils), \
            mock.patch.object(identity_swap.boto3, 'client', side_effect=lambda name, **_: clients[name]), \
            mock.patch.object(identity_swap.ConfigManager, 'get_config_setting', return_value=swap.APP_KIND), \
            mock.patch.object(identity_swap, 'yes_or_no', return_value=True), \
            mock.patch('builtins.input', return_value='yes'), \
            mock.patch.object(identity_swap, 'PRINT'):
        swap.identity_swap(**kwargs)
    return {'ecs': ecs_calls, 'application-autoscaling': autoscaling_calls,
            'cloudwatch': cloudwatch_calls, 's3': s3_calls}


def test_smaht_identity_swap_api_calls_are_all_allowed():
    """ `identity-swap <blue> <green>` for SMaHT: ECS discovery and service re-pointing, the
        global env bucket's main.ecosystem (SSE-KMS), and the indexer autoscaling policies/alarms.
    """
    from src.commands.identity_swap import SMaHTIdentitySwap

    class Swap(SMaHTIdentitySwap):
        APP_KIND = 'smaht'
    calls = _drive_identity_swap(Swap, _smaht_ecs(), {'main.ecosystem': {'ecosystem': 'blue.ecosystem'}},
                                 blue='smaht-production-blue', green='smaht-production-green')
    assert set(_names(calls['ecs'])) == {'ListClusters', 'ListServices', 'DescribeServices', 'UpdateService'}
    assert set(_names(calls['application-autoscaling'])) == {
        'RegisterScalableTarget', 'DescribeScalingPolicies', 'DeleteScalingPolicy', 'PutScalingPolicy'}
    assert set(_names(calls['cloudwatch'])) == {'DescribeAlarms', 'PutMetricAlarm'}
    puts = [params for name, params in calls['s3'] if name == 'PutObject']
    assert [(p['Bucket'], p['Key']) for p in puts] == [('smaht-production-foursight-envs', 'main.ecosystem')]
    assert puts[0]['SSEKMSKeyId'] == SMaHTIdentitySwap.SMAHT_KMS_KEY_ID
    denied = [d for service, recorded in calls.items()
              for d in _request_decisions(service, recorded) if d[2] != 'allow']
    assert not denied, denied
    # SSE-KMS upload and read of that object: data-key use through S3 (the key policy must also
    # name the role; it does for the datastore key when the role is configured).
    key = f'arn:aws:kms:{REGION}:{ACCOUNT}:key/{SMaHTIdentitySwap.SMAHT_KMS_KEY_ID}'
    for action in ('kms:GenerateDataKey', 'kms:Decrypt'):
        assert _decide(action, key, {'kms:ViaService': f's3.{REGION}.amazonaws.com'}) == 'allow'


def test_fourfront_identity_swap_api_calls_are_all_allowed():
    """ `identity-swap <blue> <green> --mirror` for Fourfront (foursight-prod-envs). """
    from src.commands.identity_swap import FFIdentitySwap

    class Swap(FFIdentitySwap):
        APP_KIND = 'ff'
    blue, green = 'c4-ecs-blue-green-FourfrontProductionBlue-AbC', 'c4-ecs-blue-green-FourfrontProductionGreen-DeF'
    services, tasks, definitions = {}, {}, []
    for cluster, color in ((blue, 'blue'), (green, 'green')):
        arns = [_ecs_service(cluster, f'{kind}Service{color}') for kind in ('Portal', 'Indexer')]
        services[_ecs_cluster(cluster)] = arns
        for arn in arns:
            kind = C4IdentitySwap._determine_service_type(arn)
            tasks[arn] = f'arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/fourfront-production-{color}-{kind}:3'
            definitions += [tasks[arn], f'arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/'
                                        f'fourfront-production-{color}-{kind}Mirror:2']
    calls = _drive_identity_swap(
        Swap, _ecs_responses(list(services), services, tasks, definitions),
        {'main.ecosystem': {'prd_env_name': 'fourfront-production-blue'},
         'green.ecosystem': {'prd_env_name': 'fourfront-production-green'}},
        blue='fourfront-production-blue', green='fourfront-production-green', mirror=True, do_legacy=False)
    assert 'ListTaskDefinitions' in _names(calls['ecs']) and 'UpdateService' in _names(calls['ecs'])
    puts = [(p['Bucket'], p['Key']) for name, p in calls['s3'] if name == 'PutObject']
    assert puts == [('foursight-prod-envs', 'main.ecosystem')]
    denied = [d for service, recorded in calls.items()
              for d in _request_decisions(service, recorded) if d[2] != 'allow']
    assert not denied, denied


def test_identity_swap_legacy_env_files_are_the_only_other_writes():
    """ `--do-legacy` (Fourfront only, documented as no longer needed) rewrites these files in the
        legacy foursight-envs bucket via upload_config; they are exactly the extra allowed writes.
    """
    for key in ('data', 'staging', 'fourfront-production-green', 'fourfront-production-blue', 'main.ecosystem'):
        assert _decide('s3:PutObject', f'arn:aws:s3:::foursight-envs/{key}', {'s3:ResourceAccount': ACCOUNT}) == 'allow'


@pytest.mark.parametrize('action, resource, context, expected', [
    # Env buckets: only the ecosystem-selection files, only in this account, never deleted.
    ('s3:PutObject', 'arn:aws:s3:::smaht-production-foursight-envs/smaht-production-blue',
     {'s3:ResourceAccount': ACCOUNT}, 'implicit-deny'),
    ('s3:PutObject', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': OTHER_ACCOUNT}, 'implicit-deny'),
    ('s3:GetObject', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': OTHER_ACCOUNT}, 'implicit-deny'),
    ('s3:PutObject', 'arn:aws:s3:::smaht-production-application-files/main.ecosystem',
     {'s3:ResourceAccount': ACCOUNT}, 'implicit-deny'),
    ('s3:DeleteObject', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': ACCOUNT}, 'deny'),
    ('s3:PutObjectAcl', 'arn:aws:s3:::smaht-production-foursight-envs/main.ecosystem',
     {'s3:ResourceAccount': ACCOUNT}, 'implicit-deny'),
    # Autoscaling: ECS service desired count only, this account and region.
    ('application-autoscaling:RegisterScalableTarget',
     f'arn:aws:application-autoscaling:{REGION}:{ACCOUNT}:scalable-target/x',
     {'application-autoscaling:service-namespace': 'dynamodb',
      'application-autoscaling:scalable-dimension': 'dynamodb:table:WriteCapacityUnits'}, 'implicit-deny'),
    ('application-autoscaling:PutScalingPolicy',
     f'arn:aws:application-autoscaling:{REGION}:{OTHER_ACCOUNT}:scalable-target/x',
     {'application-autoscaling:service-namespace': 'ecs',
      'application-autoscaling:scalable-dimension': 'ecs:service:DesiredCount'}, 'implicit-deny'),
    ('application-autoscaling:DeleteScalingPolicy',
     f'arn:aws:application-autoscaling:us-west-2:{ACCOUNT}:scalable-target/x',
     {'aws:RequestedRegion': 'us-west-2', 'application-autoscaling:service-namespace': 'ecs',
      'application-autoscaling:scalable-dimension': 'ecs:service:DesiredCount'}, 'deny'),
    # ECS: discovery in the home region; still no direct task execution.
    ('ecs:ListServices', '*', {'aws:RequestedRegion': 'us-west-2'}, 'deny'),
    ('ecs:UpdateService', f'arn:aws:ecs:{REGION}:{OTHER_ACCOUNT}:service/c/s', {}, 'implicit-deny'),
    ('ecs:RunTask', '*', {}, 'deny'),
])
def test_release_command_permissions_keep_their_scope(action, resource, context, expected):
    assert _decide(action, resource, context) == expected


def test_autoscaling_service_linked_role_can_be_created():
    resource = _iam('role/aws-service-role/ecs.application-autoscaling.amazonaws.com/'
                    'AWSServiceRoleForApplicationAutoScaling_ECSService')
    assert _decide('iam:CreateServiceLinkedRole', resource,
                   {'iam:AWSServiceName': 'ecs.application-autoscaling.amazonaws.com'}) == 'allow'


# ---------------------------------------------------------------------------------------------
# 7. README example
# ---------------------------------------------------------------------------------------------

DEPLOY_README_HEADING = '### Illustrative policy: deployment role (`*InfraDeployRole`)'


def _readme_deploy_policy() -> dict:
    text = io.open(README).read()
    assert DEPLOY_README_HEADING in text
    after = text.split(DEPLOY_README_HEADING, 1)[1]
    match = re.search(r'```json\n(.*?)\n```', after, re.DOTALL)
    assert match
    return json.loads(match.group(1))


def _placeholder(value):
    if isinstance(value, dict):
        if value == {'Ref': 'AWS::Region'}:
            return '<region>'
        if value == {'Ref': 'AWS::AccountId'}:
            return '<account-id>'
        if 'Fn::Join' in value:
            separator, parts = value['Fn::Join']
            return separator.join(_placeholder(part) for part in parts)
        return {key: _placeholder(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_placeholder(item) for item in value]
    return value


def test_readme_deploy_example_matches_the_generated_policies():
    assert _readme_deploy_policy()['Statement'] == _placeholder(_deploy_statements())


def test_readme_deploy_example_is_labelled_and_not_deployable_as_written():
    text = io.open(README).read()
    section = text.split(DEPLOY_README_HEADING, 1)[1].split('\n### ', 1)[0]
    assert 'not deployable as written' in section
    assert 'src/parts/iam.py' in section
    rendered = json.dumps(_readme_deploy_policy())
    assert '<account-id>' in rendered and '<region>' in rendered
    assert not re.search(r'\b\d{12}\b', rendered)
    # The older anchor and its diagnostic example remain.
    assert '### Illustrative policy: diagnostic role (`*DevDiagnoseRole`)' in text
