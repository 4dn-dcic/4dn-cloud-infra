import os

import pytest
from chalice.package import TemplateDeepMerger

from src.foursight_merge_template import (
    COMBINED_MERGE_TEMPLATE_NAME,
    DEFAULT_FOURSIGHT_MERGE_TEMPLATE,
    load_template,
    resolve_merge_template,
)


DEFAULT_CHECK_RUNNER_PROPERTIES = {
    'RecursiveLoop': 'Allow',
    'ReservedConcurrentExecutions': 60,
    'EventInvokeConfig': {'MaximumRetryAttempts': 1, 'MaximumEventAgeInSeconds': 3600},
}

# Modeled on the CheckRunner resource in a chalice-generated foursight sam.yaml.
CHECK_RUNNER_TEMPLATE = {
    'Resources': {
        'CheckRunner': {
            'Type': 'AWS::Serverless::Function',
            'Properties': {
                'CodeUri': './deployment.zip',
                'Handler': 'app.check_runner',
                'MemorySize': 512,
                'Runtime': 'python3.12',
                'Timeout': 900,
                'Tracing': 'PassThrough',
                'Role': {'Fn::GetAtt': ['CheckRunnerRole', 'Arn']},
                'VpcConfig': {'SecurityGroupIds': ['sg-1'], 'SubnetIds': ['subnet-1']},
            },
        },
        'CheckRunnerRole': {'Type': 'AWS::IAM::Role'},
    },
}


ALARMS = ('CheckRunnerInvocationsAlarm', 'CheckRunnerConcurrencyAlarm')


def test_default_template_allows_check_runner_recursion():
    template = load_template(DEFAULT_FOURSIGHT_MERGE_TEMPLATE)
    assert set(template['Resources']) == {'CheckRunner', *ALARMS}
    assert template['Resources']['CheckRunner'] == {'Properties': DEFAULT_CHECK_RUNNER_PROPERTIES}


def test_default_template_alarms_watch_check_runner():
    resources = load_template(DEFAULT_FOURSIGHT_MERGE_TEMPLATE)['Resources']
    for name in ALARMS:
        alarm = resources[name]
        assert alarm['Type'] == 'AWS::CloudWatch::Alarm'
        assert alarm['Properties']['Namespace'] == 'AWS/Lambda'
        assert alarm['Properties']['Dimensions'] == [{'Name': 'FunctionName', 'Value': {'Ref': 'CheckRunner'}}]
        assert 'AlarmActions' not in alarm['Properties']  # no notification target chosen yet
    assert resources['CheckRunnerInvocationsAlarm']['Properties']['MetricName'] == 'Invocations'
    concurrency = resources['CheckRunnerConcurrencyAlarm']['Properties']
    assert concurrency['MetricName'] == 'ConcurrentExecutions'
    # The concurrency alarm must fire before the reserved concurrency cap starts throttling.
    assert concurrency['Threshold'] < DEFAULT_CHECK_RUNNER_PROPERTIES['ReservedConcurrentExecutions']


def test_no_user_template_uses_default():
    path = resolve_merge_template(None, output_dir=None)
    assert path == DEFAULT_FOURSIGHT_MERGE_TEMPLATE
    assert os.path.isabs(path) and os.path.exists(path)


def test_user_template_is_combined_over_default(tmp_path):
    user = tmp_path / 'user.yaml'
    user.write_text(
        'Resources:\n'
        '  CheckRunner:\n'
        '    Properties:\n'
        '      MemorySize: 1024\n'
        '  Extra:\n'
        '    Type: AWS::SNS::Topic\n'
        '    Properties:\n'
        '      TopicName: !Ref SomeParam\n'
    )
    out = tmp_path / 'out'
    path = resolve_merge_template(str(user), output_dir=str(out))
    assert path == os.path.abspath(str(out / COMBINED_MERGE_TEMPLATE_NAME))
    combined = load_template(path)
    assert combined['Resources']['CheckRunner']['Properties'] == dict(DEFAULT_CHECK_RUNNER_PROPERTIES, MemorySize=1024)
    assert set(ALARMS) <= set(combined['Resources'])
    assert combined['Resources']['Extra']['Properties']['TopicName'] == {'Ref': 'SomeParam'}


def test_user_template_can_override_default(tmp_path):
    user = tmp_path / 'user.yaml'
    user.write_text('Resources:\n  CheckRunner:\n    Properties:\n      RecursiveLoop: Terminate\n')
    combined = load_template(resolve_merge_template(str(user), output_dir=str(tmp_path)))
    assert combined['Resources']['CheckRunner']['Properties']['RecursiveLoop'] == 'Terminate'


def test_user_template_requires_output_dir(tmp_path):
    user = tmp_path / 'user.yaml'
    user.write_text('Resources: {}\n')
    with pytest.raises(ValueError):
        resolve_merge_template(str(user), output_dir=None)


def test_merge_into_generated_template_keeps_check_runner_properties():
    merged = TemplateDeepMerger().merge(load_template(DEFAULT_FOURSIGHT_MERGE_TEMPLATE), CHECK_RUNNER_TEMPLATE)
    properties = merged['Resources']['CheckRunner']['Properties']
    expected = dict(CHECK_RUNNER_TEMPLATE['Resources']['CheckRunner']['Properties'], **DEFAULT_CHECK_RUNNER_PROPERTIES)
    assert properties == expected
    assert merged['Resources']['CheckRunner']['Type'] == 'AWS::Serverless::Function'
    assert merged['Resources']['CheckRunnerRole'] == CHECK_RUNNER_TEMPLATE['Resources']['CheckRunnerRole']
    assert set(merged['Resources']) == {'CheckRunner', 'CheckRunnerRole', *ALARMS}
