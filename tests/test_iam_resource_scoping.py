"""Shared IAM inventory policies checked against physical resources from full templates."""
import copy
import fnmatch
import json

import pytest

from src.constants import Settings
from src.parts.appconfig import C4AppConfig
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.datastore import C4Datastore
from src.parts.datastore_slim import C4DatastoreSlim
from src.parts.ecr import C4ContainerRegistry
from src.parts.iam import C4IAM
from src.parts.iam_resources import ecosystem_resources
from src.parts.srce_datastore import C4SRCEDatastore


ACCOUNT = '123456789012'
REGION = 'us-east-1'
KEYS = ['11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222']


def resolve(value):
    if isinstance(value, dict):
        if 'Ref' in value:
            return {'AWS::AccountId': ACCOUNT, 'AWS::Region': REGION}[value['Ref']]
        if 'Fn::Join' in value:
            sep, items = value['Fn::Join']
            return sep.join(resolve(item) for item in items)
        return {key: resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item) for item in value]
    return value


def statements(resource, resources):
    policies = list(resource['Properties']['Policies'])
    policies += [resources[arn['Ref']]['Properties'] for arn in resource['Properties'].get('ManagedPolicyArns', [])]
    return [resolve(statement) for policy in policies for statement in policy['PolicyDocument']['Statement']]


def allows(rules, action, arn):
    # These generated inline policies have Allow statements only and no conditions.
    return any(rule['Effect'] == 'Allow'
               and any(fnmatch.fnmatchcase(action.lower(), pattern.lower()) for pattern in rule['Action'])
               and any(fnmatch.fnmatchcase(arn, pattern) for pattern in rule['Resource']) for rule in rules)


@pytest.fixture
def inventory(synthesis_config, synthesize, monkeypatch):
    inventory = {key: set() for key in ['buckets', 'queues', 'search_domains', 'repositories', 'runtime_secrets']}
    # Appconfig synthesis normally discovers an endpoint. No other producer is stubbed.
    monkeypatch.setattr(ApplicationConfigurationSecrets, 'get_es_url', lambda: 'offline.example')
    for kind in ['cgap', 'ff', 'smaht']:
        for deployment in ['standalone', 'blue/green']:
            synthesis_config(kind, deployment)
            for cls in [C4Datastore, C4SRCEDatastore, C4DatastoreSlim, C4AppConfig, C4ContainerRegistry]:
                for resource in synthesize(cls)['Resources'].values():
                    props = resource['Properties']
                    key, field = {
                        'AWS::S3::Bucket': ('buckets', 'BucketName'),
                        'AWS::SQS::Queue': ('queues', 'QueueName'),
                        'AWS::Elasticsearch::Domain': ('search_domains', 'DomainName'),
                        'AWS::OpenSearchService::Domain': ('search_domains', 'DomainName'),
                        'AWS::ECR::Repository': ('repositories', 'RepositoryName'),
                        'AWS::SecretsManager::Secret': ('runtime_secrets', 'Name'),
                    }.get(resource['Type'], (None, None))
                    if key and not (key == 'runtime_secrets' and props[field].endswith(
                            ('Foursight', 'FalconClientID', 'FalconClientSecret'))):
                        inventory[key].add(props[field])
    inventory['runtime_secrets'].add('fourfront-mastertest')
    inventory = {key: sorted(values) for key, values in inventory.items()}
    inventory['kms_keys'] = KEYS
    return inventory


def test_policy_matches_all_producers_without_environment_revocation(synthesis_config, synthesize, inventory):
    # The SAME inventory is used in each environment; a local ENV_NAME or key override cannot
    # revoke the other environments' access via this ecosystem-wide identity.
    templates = []
    for env, key_id in [('cgap-test', KEYS[0]), ('cgap-second', KEYS[1])]:
        synthesis_config(extra={Settings.ENV_NAME: env, Settings.S3_ENCRYPT_KEY_ID: key_id,
                                Settings.IAM_ECOSYSTEM_RESOURCES: inventory})
        templates.append(synthesize(C4IAM))
    assert templates[0] == templates[1]
    resources = templates[0]['Resources']
    ecs = resources[C4IAM.ROLE_NAME]
    rules = statements(ecs, resources)
    # Resource inventories must not exceed IAM's default attachment or document-size limits.
    for resource in resources.values():
        props = resource['Properties']
        if resource['Type'] == 'AWS::IAM::ManagedPolicy':
            assert len(json.dumps(resolve(props['PolicyDocument']), separators=(',', ':'))) <= 6144
        elif resource['Type'] in ['AWS::IAM::Role', 'AWS::IAM::User']:
            size = sum(len(json.dumps(resolve(p['PolicyDocument']), separators=(',', ':')))
                       for p in props.get('Policies', []))
            assert size <= (2048 if resource['Type'] == 'AWS::IAM::User' else 10240)
            assert len(props.get('ManagedPolicyArns', [])) <= 10
    for bucket in inventory['buckets']:
        assert allows(rules, 's3:ListBucket', f'arn:aws:s3:::{bucket}')
        assert allows(rules, 's3:GetObject', f'arn:aws:s3:::{bucket}/object')
        assert not allows(rules, 's3:GetObject', f'arn:aws:s3:::{bucket}-other/object')
    for queue in inventory['queues']:
        arn = f'arn:aws:sqs:{REGION}:{ACCOUNT}:{queue}'
        assert allows(rules, 'sqs:SendMessage', arn)
        assert not allows(rules, 'sqs:SendMessage', arn + '-other')
        assert not allows(rules, 'sqs:DeleteQueue', arn)
    assert any(domain.startswith('es-') for domain in inventory['search_domains'])
    for domain in inventory['search_domains']:
        arn = f'arn:aws:es:{REGION}:{ACCOUNT}:domain/{domain}'
        assert allows(rules, 'es:ESHttpPost', arn + '/index/_search')
        assert allows(rules, 'es:DescribeDomain', arn)
        assert not allows(rules, 'es:ESHttpPost', arn + '-other/index/_search')
        assert not allows(rules, 'es:DescribeDomain', arn + '-other')
    for repo in inventory['repositories']:
        arn = f'arn:aws:ecr:{REGION}:{ACCOUNT}:repository/{repo}'
        assert allows(rules, 'ecr:BatchGetImage', arn)
        assert not allows(rules, 'ecr:BatchGetImage', arn + '-other')
        assert not allows(rules, 'ecr:PutImage', arn)
    assert any(name.startswith('C4SRCEDatastore') for name in inventory['runtime_secrets'])
    for name in inventory['runtime_secrets']:
        arn = f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{name}'
        assert allows(rules, 'secretsmanager:GetSecretValue', arn + '-aBc123')
        assert not allows(rules, 'secretsmanager:GetSecretValue', arn + 'FalconClientSecret-aBc123')
        assert not allows(rules, 'secretsmanager:GetSecretValue', arn + '-other-aBc123')
    for key in KEYS:
        assert allows(rules, 'kms:Decrypt', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/{key}')
    assert not allows(rules, 'kms:Decrypt', f'arn:aws:kms:{REGION}:{ACCOUNT}:key/other')
    for arn in [f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4AppConfigCgapTestFalconClientSecret-abc123',
                f'arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:C4AppConfigCgapTestFalconClientID-abc123']:
        assert not allows(rules, 'secretsmanager:GetSecretValue', arn)
    user = next(r for r in resources.values() if r['Type'] == 'AWS::IAM::User')
    for bucket in inventory['buckets']:
        assert allows(statements(user, resources), 's3:PutObject', f'arn:aws:s3:::{bucket}/file')
    for action in ['sqs:ListQueues', 'es:ListDomainNames', 'ecr:GetAuthorizationToken']:
        assert allows(rules, action, '*')


@pytest.mark.parametrize('serialization', [lambda x: x, json.dumps, repr])
def test_inventory_load_forms(synthesis_config, inventory, serialization):
    synthesis_config(extra={Settings.IAM_ECOSYSTEM_RESOURCES: serialization(inventory)})
    assert ecosystem_resources() == inventory


@pytest.mark.parametrize('invalid', [None, '{}', 'not-json', {'buckets': ['only-this-env']},
                                     {'typo': []}])
def test_missing_inventory_fails_closed(synthesis_config, synthesize, invalid):
    synthesis_config(extra={Settings.IAM_ECOSYSTEM_RESOURCES: invalid})
    with pytest.raises(ValueError, match='complete shared IAM resource inventory'):
        synthesize(C4IAM)


@pytest.mark.parametrize('field,value', [
    ('buckets', ['*']), ('runtime_secrets', ['C4AppConfig*']),
    ('runtime_secrets', ['C4AppConfigTestFalconClientSecret']),
    ('queues', []), ('search_domains', ['os-test*']),
    ('kms_keys', ['arn:aws:kms:us-east-1:123:key/wrong']), ('repositories', 'not-a-list'),
])
def test_invalid_or_sensitive_scope_rejected(synthesis_config, inventory, field, value):
    invalid = copy.deepcopy(inventory)
    invalid[field] = value
    synthesis_config(extra={Settings.IAM_ECOSYSTEM_RESOURCES: invalid})
    with pytest.raises(ValueError, match='iam.ecosystem_resources'):
        ecosystem_resources()


def test_bootstrap_never_emits_account_wide_kms(synthesis_config, synthesize, inventory):
    inventory['kms_keys'] = []
    synthesis_config(extra={Settings.IAM_ECOSYSTEM_RESOURCES: inventory})
    resources = synthesize(C4IAM)['Resources']
    assert not any('kms:' in action for statement in statements(resources[C4IAM.ROLE_NAME], resources)
                   for action in statement['Action'])
