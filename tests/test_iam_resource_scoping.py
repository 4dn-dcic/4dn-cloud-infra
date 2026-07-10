"""
Regression tests for SEC-1: the ECS role IAM policies must scope their resources to the
*actual* physical names of the infrastructure's secrets, queues, OpenSearch domain, and ECR
repositories -- not to the placeholder 'c4-*'/'c4*' prefixes that match nothing real and would
cut every ECS task off from its configuration, queues, search domain, and images.

The physical names these assertions target come from:
  - secrets:   C4AppConfig<Env> (GAC/Foursight/Falcon), C4Datastore<Env>RDSSecret  (appconfig/datastore)
  - SQS:       {env_name}-<suffix>                                                  (datastore.build_sqs_instance)
  - OpenSearch: os-{env_name}                                                       (datastore.opensearch_instance)
  - ECR:       {env_name} + ecr.ECR_REPO_NAMES                                      (ecr.build_template)
"""
import json
from unittest import mock

from src.parts import iam as iam_mod
from src.parts.iam import C4IAM
from src.parts.ecr import ECR_REPO_NAMES
from src.c4name import C4Name
from src.part import C4Tags, C4Account


TEST_ENV_NAME = 'cgap-build'


def _make_iam_part():
    name = C4Name('c4-iam-main', title_token='C4IAMMain')
    return C4IAM(name=name, tags=C4Tags(),
                 account=C4Account(account_number='123456789', creds_file='/dev/null'))


def _policy_json(policy):
    return json.dumps(policy.to_dict())


def test_secret_manager_policy_scoped_to_real_secret_prefixes():
    part = _make_iam_part()
    with mock.patch.object(iam_mod.ConfigManager, 'get_config_setting', return_value=TEST_ENV_NAME):
        doc = _policy_json(part.ecs_secret_manager_policy())
    # Covers GAC/Foursight/Falcon (C4AppConfig*) and RDS master secret (C4Datastore*).
    assert 'C4AppConfig*' in doc
    assert 'C4Datastore*' in doc
    # The old placeholder must be gone -- it matched no real secret.
    assert 'c4-*' not in doc


def test_sqs_policy_scoped_to_env_queues_and_listqueues_separated():
    part = _make_iam_part()
    with mock.patch.object(iam_mod.ConfigManager, 'get_config_setting', return_value=TEST_ENV_NAME):
        policy = part.ecs_sqs_policy().to_dict()
    doc = json.dumps(policy)
    # Queues are named '{env_name}-<suffix>'.
    assert f'{TEST_ENV_NAME}-*' in doc
    assert 'c4-*' not in doc
    # ListQueues is account-level and must live in its own '*'-scoped statement.
    statements = policy['PolicyDocument']['Statement']
    listqueues_stmts = [s for s in statements if 'sqs:ListQueues' in s['Action']]
    assert len(listqueues_stmts) == 1
    assert listqueues_stmts[0]['Resource'] == ['*']
    # The resource-scoped statement must NOT also grant ListQueues.
    scoped_stmts = [s for s in statements if 'sqs:SendMessage' in s['Action']]
    assert len(scoped_stmts) == 1
    assert 'sqs:ListQueues' not in scoped_stmts[0]['Action']


def test_es_policy_scoped_to_env_domain_and_account_actions_separated():
    part = _make_iam_part()
    with mock.patch.object(iam_mod.ConfigManager, 'get_config_setting', return_value=TEST_ENV_NAME):
        policy = part.ecs_es_policy().to_dict()
    doc = json.dumps(policy)
    # Domain is named 'os-{env_name}'.
    assert f'os-{TEST_ENV_NAME}*' in doc
    assert 'domain/c4*' not in doc
    # Account-level Describe/List actions live in their own '*'-scoped statement.
    statements = policy['PolicyDocument']['Statement']
    account_stmts = [s for s in statements if 'es:ListDomainNames' in s['Action']]
    assert len(account_stmts) == 1
    assert account_stmts[0]['Resource'] == ['*']


def test_ecr_policy_scoped_to_exactly_the_repos_that_exist():
    part = _make_iam_part()
    with mock.patch.object(iam_mod.ConfigManager, 'get_config_setting', return_value=TEST_ENV_NAME):
        policy = part.ecs_ecr_policy().to_dict()
    doc = json.dumps(policy)
    assert 'repository/c4-*' not in doc
    # Env portal repo plus every fixed pipeline/sidecar repo must be present.
    assert f'repository/{TEST_ENV_NAME}' in doc
    for repo in ECR_REPO_NAMES:
        assert f'repository/{repo}' in doc, f'ECR repo {repo!r} not covered by IAM scope'
    # GetAuthorizationToken is account-level and stays scoped to '*'.
    statements = policy['PolicyDocument']['Statement']
    auth_stmts = [s for s in statements if any('GetAuthorizationToken' in a for a in s['Action'])]
    assert len(auth_stmts) == 1
    assert auth_stmts[0]['Resource'] == ['*']
