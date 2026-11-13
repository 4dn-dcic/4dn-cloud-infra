"""
``foursight.api_source_cidrs``: the opt-in API Gateway source-CIDR restriction for ``foursight-srce``.

Documentation-range addresses only (RFC 5737 / RFC 3849); no deployment's real CIDRs belong here.
"""
import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
import yaml
from unittest import mock

from src.base import ConfigManager
from src.constants import Settings
from src.foursight_api_policy import (POLICY_FILE_NAME, FoursightApiSourceCidrsError, apply_to_chalice_config,
                                      configured_source_cidrs, parse_source_cidrs, source_cidr_policy)
from src.stack import C4FoursightSMAHTSRCEStack

CIDR_A = '192.0.2.10/32'
CIDR_B = '198.51.100.0/24'
CIDR_V6 = '2001:db8::/48'


# ---------------------------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------------------------

def test_absent_setting_means_no_restriction():
    assert parse_source_cidrs(None) is None
    with mock.patch.object(ConfigManager, 'get_config_setting', lambda key, default=None, **kw: default):
        assert configured_source_cidrs() is None


@pytest.mark.parametrize('value', [
    [CIDR_A, CIDR_B],
    f"['{CIDR_A}', '{CIDR_B}']",  # how a config.json list arrives (CLN-10, src/base.py)
    f'["{CIDR_A}", "{CIDR_B}"]',
    f'{CIDR_A}, {CIDR_B}',
    f'192.0.2.10, {CIDR_B}, {CIDR_A}',  # bare address -> /32; duplicates dropped, order kept
])
def test_accepted_forms_normalize_to_the_same_list(value):
    assert parse_source_cidrs(value) == [CIDR_A, CIDR_B]


def test_ipv6_ranges_are_accepted_alongside_ipv4():
    assert parse_source_cidrs([CIDR_A, CIDR_V6]) == [CIDR_A, CIDR_V6]


@pytest.mark.parametrize('value, reason', [
    ('', 'empty'), ('[]', 'empty'), ([], 'empty'), (f'{CIDR_A},', 'empty'),
    ('not-a-cidr', 'not a valid CIDR'), ('192.0.2.10/33', 'not a valid CIDR'),
    ('192.0.2.10/24', 'not a valid CIDR'),  # host bits set: ambiguous intent, never silently widened
    ('[192.0.2.10/32', 'not a valid list'),
    ('0.0.0.0/0', 'every address'), ('::/0', 'every address'),
    ('10.1.0.0/16', 'not a public'), ('172.16.5.0/24', 'not a public'), ('192.168.0.0/16', 'not a public'),
    ('100.64.0.0/10', 'not a public'), ('127.0.0.1', 'not a public'), ('169.254.0.0/16', 'not a public'),
    ('fd00::/8', 'not a public'), ('fe80::/64', 'not a public'), ('::1', 'not a public'),
    ('224.0.0.0/4', 'not a public'), ('8.0.0.0/6', 'not a public'),  # 8.0.0.0/6 contains 10.0.0.0/8
])
def test_unsafe_or_malformed_values_are_rejected_with_the_setting_named(value, reason):
    with pytest.raises(FoursightApiSourceCidrsError) as e:
        parse_source_cidrs(value)
    assert reason in str(e.value)
    assert Settings.FOURSIGHT_API_SOURCE_CIDRS in str(e.value) or 'chalice' in str(e.value)


# ---------------------------------------------------------------------------------------------
# The policy
# ---------------------------------------------------------------------------------------------

def test_policy_is_the_standard_source_ip_pattern_on_every_stage_method_and_path():
    policy = source_cidr_policy([CIDR_A, CIDR_V6])
    allow, deny = policy['Statement']
    assert len(policy['Statement']) == 2
    assert allow == {'Sid': 'AllowInvoke', 'Effect': 'Allow', 'Principal': '*',
                     'Action': 'execute-api:Invoke', 'Resource': 'execute-api:/*'}
    assert deny['Effect'] == 'Deny' and deny['Principal'] == '*' and deny['Action'] == 'execute-api:Invoke'
    # One resource for all stages: no stage (e.g. SAM's implicit 'Stage') escapes the deny.
    assert deny['Resource'] == 'execute-api:/*'
    assert deny['Condition'] == {'NotIpAddress': {'aws:SourceIp': [CIDR_A, CIDR_V6]}}


# ---------------------------------------------------------------------------------------------
# The chalice config the SRCE package path writes
# ---------------------------------------------------------------------------------------------

def package_srce(api_source_cidrs, tmpdir, **extra):
    """ Run the real SRCE build_config_and_package() with only subprocesses and the config path
        stubbed; return the chalice config it wrote. """
    package_deploy = C4FoursightSMAHTSRCEStack.PackageDeploy
    config_path = os.path.join(tmpdir, 'config.json')
    args = argparse.Namespace(stack='foursight-srce', merge_template=None, output_file=tmpdir,
                              stage='prod', trial=True)
    with mock.patch('foursight_core.deploy.subprocess_call', return_value=0), \
            mock.patch.object(package_deploy, 'get_config_filepath', classmethod(lambda cls: config_path)):
        package_deploy.build_config_and_package(
            args, identity='C4AppConfigTestFoursight', stack_name='c4-foursight-srce-test-stack',
            merge_template=None, output_file=tmpdir, stage='prod', trial=True,
            global_env_bucket='test-foursight-envs', security_ids=['sg-0aaaaaaaaaaaaaaa1'],
            subnet_ids=['subnet-0aaaaaaaaaaaaaaa1'], trial_creds={'S3_ENCRYPT_KEY': 'x'},
            api_source_cidrs=api_source_cidrs, **extra)
    with open(config_path) as fp:
        return json.load(fp)


@pytest.fixture
def pristine_srce_config_base():
    """ CONFIG_BASE is class state; restore it so tests cannot leak into each other. """
    saved = copy.deepcopy(C4FoursightSMAHTSRCEStack.PackageDeploy.CONFIG_BASE)
    yield C4FoursightSMAHTSRCEStack.PackageDeploy.CONFIG_BASE
    C4FoursightSMAHTSRCEStack.PackageDeploy.CONFIG_BASE.clear()
    C4FoursightSMAHTSRCEStack.PackageDeploy.CONFIG_BASE.update(saved)


def test_absent_leaves_the_chalice_config_without_any_api_policy(pristine_srce_config_base):
    with tempfile.TemporaryDirectory() as tmpdir:
        config = package_srce(None, tmpdir)
        assert not os.path.exists(os.path.join(tmpdir, POLICY_FILE_NAME))
    for stage in config['stages'].values():
        assert 'api_gateway_policy_file' not in stage


def test_configured_cidrs_reach_both_chalice_stages(pristine_srce_config_base):
    with tempfile.TemporaryDirectory() as tmpdir:
        config = package_srce([CIDR_A, CIDR_B], tmpdir)
        with open(os.path.join(tmpdir, POLICY_FILE_NAME)) as fp:
            assert json.load(fp) == source_cidr_policy([CIDR_A, CIDR_B])
    assert {name: stage['api_gateway_policy_file'] for name, stage in config['stages'].items()} == \
        {'dev': POLICY_FILE_NAME, 'prod': POLICY_FILE_NAME}


def test_removing_the_setting_removes_the_policy_from_the_next_package(pristine_srce_config_base):
    with tempfile.TemporaryDirectory() as tmpdir:
        package_srce([CIDR_A], tmpdir)
        config = package_srce(None, tmpdir)
        assert not os.path.exists(os.path.join(tmpdir, POLICY_FILE_NAME))
    for stage in config['stages'].values():
        assert 'api_gateway_policy_file' not in stage


def test_an_existing_stage_policy_is_never_replaced(pristine_srce_config_base):
    pristine_srce_config_base['stages']['prod']['api_gateway_policy_file'] = 'someone-elses-policy.json'
    with tempfile.TemporaryDirectory() as tmpdir:
        for cidrs in ([CIDR_A], None):
            with pytest.raises(FoursightApiSourceCidrsError, match='someone-elses-policy.json'):
                package_srce(cidrs, tmpdir)
        assert not os.path.exists(os.path.join(tmpdir, POLICY_FILE_NAME))
    assert pristine_srce_config_base['stages']['prod']['api_gateway_policy_file'] == 'someone-elses-policy.json'


def test_a_private_endpoint_default_policy_is_never_replaced():
    config_base = {'stages': {'prod': {'api_gateway_endpoint_type': 'PRIVATE'}}}
    with tempfile.TemporaryDirectory() as tmpdir:
        with pytest.raises(FoursightApiSourceCidrsError, match='PRIVATE'):
            apply_to_chalice_config(config_base, tmpdir, [CIDR_A])


def test_the_stack_validates_at_construction_and_passes_the_cidrs_to_packaging():
    stack = C4FoursightSMAHTSRCEStack.__new__(C4FoursightSMAHTSRCEStack)
    stack.name = mock.Mock(stack_name='c4-foursight-srce-test-stack')
    stack.security_ids, stack.subnet_ids = ['sg-0aaaaaaaaaaaaaaa1'], ['subnet-0aaaaaaaaaaaaaaa1']
    stack.global_env_bucket, stack.trial_creds = 'test-foursight-envs', {}
    stack.api_source_cidrs = [CIDR_A]
    args = argparse.Namespace(foursight_identity='C4AppConfigTestFoursight', merge_template=None,
                              output_file='out', stage='prod', trial=True)
    with mock.patch.object(C4FoursightSMAHTSRCEStack.PackageDeploy, 'build_config_and_package') as package:
        stack.package_foursight_stack(args)
    assert package.call_args.kwargs['api_source_cidrs'] == [CIDR_A]


# ---------------------------------------------------------------------------------------------
# What actually deploys: chalice package -> SAM transform -> CloudFormation
#
# A resource policy reaches callers only through a stage's deployment snapshot. These run the real
# chalice packager and the real SAM translator (no AWS) on a minimal app with the same stage layout
# as Foursight ('api' stage, autogen_policy off), to show that the policy is in the API definition,
# that both stages serve the same deployment, and that adding, changing or removing the setting
# changes the deployment CloudFormation creates.
# ---------------------------------------------------------------------------------------------

def offline_aws_env():
    """ chalice only asks botocore for a region name (to pick the Lambda service principal); pin it,
        and keep the developer's or another test's AWS settings and credentials out of the run. """
    env = {k: v for k, v in os.environ.items() if not k.startswith('AWS_')}
    env.update(AWS_DEFAULT_REGION='us-east-1', AWS_CONFIG_FILE=os.devnull, AWS_SHARED_CREDENTIALS_FILE=os.devnull)
    return env


def deployed_api(tmp_path, cidrs):
    project = tmp_path / 'project'
    (project / '.chalice').mkdir(parents=True, exist_ok=True)
    (project / 'app.py').write_text("from chalice import Chalice\napp = Chalice(app_name='fs')\n\n\n"
                                    "@app.route('/')\ndef index():\n    return {}\n")
    (project / 'requirements.txt').write_text('')
    (project / '.chalice' / 'policy-prod.json').write_text(json.dumps(
        {'Version': '2012-10-17', 'Statement': [{'Effect': 'Allow', 'Action': 'logs:*', 'Resource': '*'}]}))
    config_base = {'version': '2.0', 'app_name': 'fs',
                   'stages': {'prod': {'api_gateway_stage': 'api', 'autogen_policy': False}}}
    apply_to_chalice_config(config_base, str(project / '.chalice'), cidrs)
    (project / '.chalice' / 'config.json').write_text(json.dumps(config_base))
    out = Path(tempfile.mkdtemp(dir=tmp_path)) / 'package'
    command = [sys.executable, '-c', 'import sys; from chalice.cli import main; sys.exit(main())',
               'package', '--stage', 'prod', '--pkg-format', 'cloudformation', '--template-format', 'yaml', str(out)]
    result = subprocess.run(command, cwd=project, capture_output=True, text=True, env=offline_aws_env())
    assert result.returncode == 0, result.stderr[-2000:]
    sam = yaml.safe_load((out / 'sam.yaml').read_text())
    for resource in sam['Resources'].values():
        if resource['Type'] == 'AWS::Serverless::Function':
            resource['Properties']['CodeUri'] = 's3://bucket/deployment.zip'  # set by `cloudformation package`

    from samtranslator.translator.transform import transform

    class NoManagedPolicies:
        def load(self):
            return {}

    cfn = transform(sam, {'AWS::Region': 'us-east-1', 'AWS::AccountId': '123456789012',
                          'AWS::Partition': 'aws'}, NoManagedPolicies())['Resources']
    by_type = {}
    for logical_id, resource in cfn.items():
        by_type.setdefault(resource['Type'], {})[logical_id] = resource['Properties']
    return by_type


@pytest.mark.parametrize('cidrs', [[CIDR_A, CIDR_V6]])
def test_generated_template_carries_the_policy_on_every_stage(tmp_path, cidrs):
    api = deployed_api(tmp_path, cidrs)
    (rest_api,) = api['AWS::ApiGateway::RestApi'].values()
    assert rest_api['Body']['x-amazon-apigateway-policy'] == source_cidr_policy(cidrs)
    (deployment_id, deployment), = api['AWS::ApiGateway::Deployment'].items()
    (stage,) = api['AWS::ApiGateway::Stage'].values()
    # The only two stages: SAM's implicit 'Stage' (on the Deployment) and chalice's 'api'. Both
    # serve the one deployment, whose snapshot includes the API-level policy above.
    assert deployment['StageName'] == 'Stage'
    assert stage['StageName'] == 'api' and stage['DeploymentId'] == {'Ref': deployment_id}


def test_adding_changing_or_removing_the_setting_creates_a_new_deployment(tmp_path):
    deployments = [set(deployed_api(tmp_path, cidrs)['AWS::ApiGateway::Deployment'])
                   for cidrs in (None, [CIDR_A], [CIDR_A, CIDR_B])]
    assert all(len(d) == 1 for d in deployments)
    assert len(set.union(*deployments)) == 3
    unrestricted = deployed_api(tmp_path, None)
    assert set(unrestricted['AWS::ApiGateway::Deployment']) == deployments[0]
    (rest_api,) = unrestricted['AWS::ApiGateway::RestApi'].values()
    assert 'x-amazon-apigateway-policy' not in rest_api['Body']
