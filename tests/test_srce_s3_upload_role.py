from unittest import mock

import pytest

from src.constants import Settings
from src.parts.appconfig import C4AppConfig
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.datastore import C4Datastore, C4DatastoreExports
from src.parts.srce_datastore import C4SRCEDatastore
from src.exports import C4DatastoreExportsMixin
from src.names import Names
from troposphere import Template


def _find_intrinsics(value, key):
    if isinstance(value, dict):
        found = []
        for name, item in value.items():
            if name == key:
                found.append(item)
            found.extend(_find_intrinsics(item, key))
        return found
    if isinstance(value, list):
        return [match for item in value for match in _find_intrinsics(item, key)]
    return []


def _find_resources(template, resource_type):
    return [(logical_id, resource) for logical_id, resource in template['Resources'].items()
            if resource['Type'] == resource_type]


def _synthesize_srce_datastore(env_name):
    from src.part import C4Account, C4Tags

    part = C4SRCEDatastore(
        name=Names.srce_datastore_stack_name_object(env_name), tags=C4Tags(),
        account=C4Account(account_number='123456789012', creds_file='/dev/null'))
    return part.build_template(Template()).to_dict()


def test_srce_datastore_creates_scoped_upload_role_and_export(synthesis_config, synthesize):
    env_name = 'smaht-dev-srce'
    synthesis_config(kind='smaht', extra={Settings.ENV_NAME: env_name})
    template = _synthesize_srce_datastore(env_name)

    roles = _find_resources(template, 'AWS::IAM::Role')
    upload_role_id, upload_role = next(
        (logical_id, role) for logical_id, role in roles
        if role['Properties'].get('RoleName') == f'c4-srce-s3-upload-{env_name}')
    role_properties = upload_role['Properties']
    trust = role_properties['AssumeRolePolicyDocument']['Statement']
    assert len(trust) == 1
    assert trust[0]['Action'] == ['sts:AssumeRole']
    assert set(trust[0]['Principal']) == {'AWS'}
    assert 'ECSAssumedIAMRole' in str(trust[0]['Principal']['AWS'])

    policy = role_properties['Policies'][0]['PolicyDocument']['Statement']
    s3_objects = next(statement for statement in policy if 's3:GetObject' in statement['Action'])
    s3_bucket = next(statement for statement in policy if statement['Action'] == 's3:ListBucket')
    assert s3_objects['Action'] == [
        's3:GetObject', 's3:PutObject', 's3:AbortMultipartUpload'
    ]
    assert s3_objects['Resource'] == f'arn:aws:s3:::{env_name}-application-files/*'
    assert s3_bucket['Resource'] == f'arn:aws:s3:::{env_name}-application-files'
    assert all('DeleteObject' not in str(statement['Action']) for statement in policy)
    assert not any(action in str(statement['Action']) for statement in policy
                   for action in ['s3:ListBucketMultipartUploads', 's3:ListMultipartUploadParts'])

    kms_statement = next(statement for statement in policy if 'kms:Decrypt' in statement['Action'])
    assert kms_statement['Action'] == [
        'kms:Decrypt', 'kms:GenerateDataKey'
    ]
    assert isinstance(kms_statement['Resource'], dict) and 'Fn::GetAtt' in kms_statement['Resource']

    kms_keys = _find_resources(template, 'AWS::KMS::Key')
    assert len(kms_keys) == 1
    _, kms_key = kms_keys[0]
    upload_key_statement = next(statement for statement in kms_key['Properties']['KeyPolicy']['Statement']
                                if statement.get('Sid') == 'Allow SRCE S3 upload role to use the key')
    assert upload_key_statement['Principal'] == {'AWS': '*'}
    assert upload_key_statement['Action'] == ['kms:Decrypt', 'kms:GenerateDataKey']
    assert upload_key_statement['Condition']['ArnEquals']['aws:PrincipalArn']
    assert f'c4-srce-s3-upload-{env_name}' in str(
        upload_key_statement['Condition']['ArnEquals']['aws:PrincipalArn'])

    output_id = Names.srce_datastore_stack_name_object(env_name).logical_id(
        C4DatastoreExports.S3_UPLOAD_ROLE_ARN)
    output = template['Outputs'][output_id]
    assert output['Value'] == {'Fn::GetAtt': [upload_role_id, 'Arn']}
    assert C4DatastoreExports.S3_UPLOAD_ROLE_ARN in str(output['Export'])


@pytest.mark.parametrize('deployment,expected_imports', [('standalone', 1), ('blue/green', 2)])
def test_srce_appconfig_imports_the_upload_role_for_gac_only(synthesis_config, synthesize, deployment,
                                                             expected_imports):
    env_name = 'smaht-dev-srce'
    synthesis_config(kind='smaht', deployment=deployment, extra={Settings.ENV_NAME: env_name})
    with mock.patch.object(ApplicationConfigurationSecrets, 'get_es_url', return_value='es.example:443'):
        template = synthesize(C4AppConfig)

    secrets = [resource['Properties'] for _, resource
               in _find_resources(template, 'AWS::SecretsManager::Secret')]
    imports = [name for secret in secrets
               for name in _find_intrinsics(secret['SecretString'], 'Fn::ImportValue')]
    expected_export = (
        f'c4-srce-datastore-{env_name}-stack-{C4DatastoreExportsMixin.S3_UPLOAD_ROLE_ARN}'
    )
    datastore_template = _synthesize_srce_datastore(env_name)
    datastore_stack_name = Names.srce_datastore_stack_name_object(env_name)
    datastore_output_id = datastore_stack_name.logical_id(
        C4DatastoreExports.S3_UPLOAD_ROLE_ARN)
    output_export = datastore_template['Outputs'][datastore_output_id]['Export']['Name']['Fn::Sub']
    synthesized_datastore_export = output_export.replace(
        '${AWS::StackName}', datastore_stack_name.stack_name)
    assert synthesized_datastore_export == expected_export
    assert imports == [expected_export] * expected_imports
    gac_secrets = [secret for secret in secrets if 'foursight configuration' not in secret['Description']]
    foursight_secret = next(secret for secret in secrets if 'foursight configuration' in secret['Description'])
    assert len(gac_secrets) == expected_imports
    assert not _find_intrinsics(foursight_secret['SecretString'], 'Fn::ImportValue')
    assert 'S3_UPLOAD_ROLE_ARN' in str(gac_secrets)
    assert f'c4-srce-s3-upload-{env_name}' not in str(gac_secrets)


@pytest.mark.parametrize('kind,env_name', [
    ('cgap', 'cgap-test'),
    ('ff', 'fourfront-test'),
    ('smaht', 'smaht-test'),
    ('cgap', 'cgap-dev-srce'),
    ('ff', 'fourfront-dev-srce'),
])
def test_non_srce_variants_do_not_get_the_upload_role_setting(synthesis_config, synthesize, kind, env_name):
    synthesis_config(kind=kind, extra={Settings.ENV_NAME: env_name})
    with mock.patch.object(ApplicationConfigurationSecrets, 'get_es_url', return_value='es.example:443'):
        template = synthesize(C4AppConfig)

    secret_strings = [resource['Properties']['SecretString']
                      for _, resource in _find_resources(template, 'AWS::SecretsManager::Secret')
                      if 'SecretString' in resource['Properties']]
    assert not _find_intrinsics(secret_strings, 'Fn::ImportValue')
    assert all('S3_UPLOAD_ROLE_ARN' not in str(secret_string) for secret_string in secret_strings)


def test_standard_datastore_does_not_create_the_srce_upload_role(synthesis_config, synthesize):
    synthesis_config(kind='cgap', extra={Settings.ENV_NAME: 'cgap-test'})
    template = synthesize(C4Datastore)

    assert not any(resource['Type'] == 'AWS::IAM::Role' and
                   'S3UploadRole' in resource['Properties'].get('RoleName', '')
                   for resource in template['Resources'].values())
    assert not any(C4DatastoreExports.S3_UPLOAD_ROLE_ARN in str(output['Export'])
                   for output in template['Outputs'].values())


def test_srce_datastore_requests_named_iam_capability(synthesis_config):
    synthesis_config(kind='smaht', extra={Settings.ENV_NAME: 'smaht-dev-srce'})
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import c4_alpha_stack_srce_datastore

    stack = c4_alpha_stack_srce_datastore(C4Account(account_number='123456789012', creds_file='/dev/null'))
    assert C4Client.build_capability_param(stack) == f'--capabilities {C4Client.CAPABILITY_NAMED_IAM}'


@pytest.mark.parametrize('kind,env_name,expected_count', [
    ('smaht', 'smaht-dev-srce', 1),
    ('smaht', 'smaht-test', 0),
    ('cgap', 'cgap-test-srce', 0),
    ('ff', 'fourfront-test-srce', 0),
])
def test_ecs_task_role_assume_permission_is_srce_only(synthesis_config, synthesize, kind, env_name, expected_count):
    synthesis_config(kind=kind, extra={Settings.ENV_NAME: env_name})
    from src.parts.iam import C4IAM
    template = synthesize(C4IAM)

    policies = [policy for _, role in _find_resources(template, 'AWS::IAM::Role')
                for policy in role['Properties'].get('Policies', [])
                if policy['PolicyName'] == f'{env_name}-AssumeSRCEFileUploadRole']
    assert len(policies) == expected_count
    if expected_count:
        statement = policies[0]['PolicyDocument']['Statement'][0]
        assert statement['Action'] == 'sts:AssumeRole'
        assert statement['Resource']['Fn::Join'][1][-1] == f'c4-srce-s3-upload-{env_name}'
