"""Full-template contracts for the PR97 review blockers, not isolated method snapshots."""
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from troposphere import Template

from src.base import ConfigManager
from src.cli import C4Client
from src.exceptions import CLIException
from src.parts.codebuild import C4CodeBuild
from src.parts.datastore import C4Datastore
from src.parts.datastore_slim import C4DatastoreSlim
from src.parts.ecs import C4ECSApplication
from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.fourfront_ecs import FourfrontECSApplication
from src.parts.network import C4Network
from src.parts.logging import C4Logging
from src.parts.shared_secrets import C4SharedSecrets
from src.parts.srce_datastore import C4SRCEDatastore
from src.parts.srce_ecs import C4SRCEECSApplication
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen
from src.parts.srce_network import C4SRCENetwork


CERT = 'arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000'


def assert_reference_integrity(template):
    resources = template.get('Resources', {})
    known = set(resources) | set(template.get('Parameters', {}))

    def visit(value):
        if isinstance(value, dict):
            if 'Ref' in value:
                assert value['Ref'] in known or value['Ref'].startswith('AWS::'), value
            if 'Fn::GetAtt' in value:
                target = value['Fn::GetAtt']
                assert (target[0] if isinstance(target, list) else target.split('.')[0]) in resources
            for key, item in value.items():
                if key == 'DependsOn':
                    for dep in item if isinstance(item, list) else [item]:
                        # ECS ContainerDefinition DependsOn is a different shape/namespace.
                        if isinstance(dep, str):
                            assert dep in resources, dep
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(template)


@pytest.mark.parametrize('kind', ['cgap', 'ff', 'smaht'])
@pytest.mark.parametrize('variant', ['standalone', 'blue/green', 'srce', 'srce-blue/green'])
@pytest.mark.parametrize('certificate', [None, CERT])
@pytest.mark.parametrize('falcon', [False, True])
def test_full_ecs_listener_graph(synthesis_config, synthesize, kind, variant, certificate, falcon):
    bg = 'blue/green' in variant
    srce = variant.startswith('srce')
    synthesis_config(kind, 'blue/green' if bg else 'standalone', {
        'ecs.lb_certificate_arn': certificate, 'crowdstrike.enabled': falcon,
        'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1', 'vpc.cidr': '10.10.0.0/16',
    })
    cls = (SRCEECSBlueGreen if bg else C4SRCEECSApplication) if srce else (
        ECSBlueGreen if bg else FourfrontECSApplication if kind == 'ff' else C4ECSApplication)
    template = synthesize(cls)
    assert_reference_integrity(template)
    resources = template['Resources']
    listeners = {key: res['Properties'] for key, res in resources.items()
                 if res['Type'] == 'AWS::ElasticLoadBalancingV2::Listener'}
    assert len(listeners) == (2 if bg else 1) * (2 if certificate else 1)
    portals = [res for res in resources.values()
               if res['Type'] == 'AWS::ECS::Service' and res['Properties'].get('LoadBalancers')]
    assert len(portals) == (2 if bg else 1)
    for service in portals:
        group = service['Properties']['LoadBalancers'][0]['TargetGroupArn']
        listener = listeners[service['DependsOn'][0]]
        assert listener['DefaultActions'] == [{'Type': 'forward', 'TargetGroupArn': group}]
        assert listener['Protocol'] == ('HTTPS' if certificate else 'HTTP')
        assert listener['Port'] == (443 if certificate else 80)
        if certificate:
            assert listener['Certificates'] == [{'CertificateArn': certificate}]
            assert listener['SslPolicy'] == C4ECSApplication.LB_SSL_POLICY
            redirects = [other for other in listeners.values() if other['Protocol'] == 'HTTP'
                         and other['LoadBalancerArn'] == listener['LoadBalancerArn']]
            assert len(redirects) == 1
            assert redirects[0]['DefaultActions'][0]['RedirectConfig']['Protocol'] == 'HTTPS'
    for output in template['Outputs'].values():
        assert output['Value']['Fn::Join'][1][0] == ('https://' if certificate else 'http://')


@pytest.mark.parametrize('cls', [C4Datastore, C4SRCEDatastore, C4DatastoreSlim])
@pytest.mark.parametrize('version', [None, '14.4', '16.6', '17.6'])
@pytest.mark.parametrize('deployment', ['standalone', 'blue/green'])
def test_rds_configured_version_and_group(synthesis_config, synthesize, cls, version, deployment):
    synthesis_config('ff' if cls is C4DatastoreSlim else 'smaht', deployment,
                     {'rds.postgres_version': version})
    template = synthesize(cls)
    assert_reference_integrity(template)
    resources = template['Resources']
    db = next(res['Properties'] for res in resources.values() if res['Type'] == 'AWS::RDS::DBInstance')
    group = resources[db['DBParameterGroupName']['Ref']]['Properties']
    assert db['EngineVersion'] == (version or '17.6')
    assert group['Family'] == 'postgres' + db['EngineVersion'].split('.')[0]
    with pytest.raises(ValueError, match='rds.postgres_version'):
        cls.rds_postgres_version_for_instance('13.0')


@pytest.mark.parametrize('cls', [C4Logging, C4SharedSecrets])
@pytest.mark.parametrize('kind', ['cgap', 'ff', 'smaht'])
@pytest.mark.parametrize('deployment', ['standalone', 'blue/green'])
def test_other_core_stack_synthesis(synthesis_config, synthesize, cls, kind, deployment):
    synthesis_config(kind, deployment)
    assert_reference_integrity(synthesize(cls))


@pytest.mark.parametrize('enabled', [False, True])
def test_network_iam_capability_matches_actual_resources(synthesis_config, synthesize, enabled):
    synthesis_config(extra={'network.flow_logs.enabled': enabled})
    template = synthesize(C4Network)
    assert_reference_integrity(template)
    stack = SimpleNamespace(template=SimpleNamespace(to_dict=lambda: template), name=C4Network.suggest_stack_name())
    assert C4Client.build_capability_param(stack) == ('--capabilities CAPABILITY_IAM' if enabled else '')


def _import_strings(value):
    if isinstance(value, dict):
        if 'Fn::ImportValue' in value:
            yield value['Fn::ImportValue']['Fn::Sub']
        for item in value.values():
            yield from _import_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _import_strings(item)


@pytest.mark.parametrize('kind', ['cgap', 'ff', 'smaht'])
@pytest.mark.parametrize('srce', [False, True])
@pytest.mark.parametrize('deployment', ['standalone', 'blue/green'])
def test_codebuild_attached_roles_and_network(synthesis_config, synthesize, monkeypatch, kind, srce, deployment):
    synthesis_config(kind, deployment, {
        'vpc.id': 'vpc-0aaaaaaaaaaaaaaa1' if srce else None, 'vpc.cidr': '10.10.0.0/16',
    })
    template = synthesize(C4CodeBuild)
    assert_reference_integrity(template)
    resources = template['Resources']
    for project in [r['Properties'] for r in resources.values() if r['Type'] == 'AWS::CodeBuild::Project']:
        role_id, attribute = project['ServiceRole']['Fn::GetAtt']
        assert attribute == 'Arn'
        role = resources[role_id]['Properties']
        assert not role.get('ManagedPolicyArns')
        secret_policies = [p for p in role['Policies'] if p['PolicyName'] == 'CBExternalSecretsAccess']
        assert len(secret_policies) == 1
        permitted = set(_import_strings(secret_policies))
        delivered = set(_import_strings([var for var in project['Environment']['EnvironmentVariables']
                                        if var.get('Type') == 'SECRETS_MANAGER']))
        assert permitted == delivered  # both allowed AND denied, from the role actually attached
        is_sensor_build = project['Name'].endswith('-pipeline-builder') and '-external-' not in project['Name']
        assert any('FalconClientSecret' in arn for arn in permitted) == is_sensor_build
        if not is_sensor_build:
            assert not any('Falcon' in arn for arn in permitted)
        if '-builder' in project['Name']:
            assert role_id.endswith('Builder')

    run = Mock()
    monkeypatch.setattr(C4Client, 'run_command', run)
    monkeypatch.setattr(ConfigManager, 'get_aws_creds_dir', lambda: '/offline/creds')
    stack = SimpleNamespace(name=C4CodeBuild.suggest_stack_name(), template=SimpleNamespace(to_dict=lambda: template))
    C4Client.upload_cloudformation_template(stack=stack, file_path='/offline/codebuild.json')
    command = run.call_args.args[0]
    network_name = 'c4-srce-network-main-stack' if srce else 'c4-network-main-stack'
    assert f'"NetworkStackNameParameter={network_name}"' in command
    assert 'DBNetworkStackNameParameter=' not in command
    assert 'ComputeNetworkStackNameParameter=' not in command
    assert '--no-execute-changeset' in command
    assert '--capabilities CAPABILITY_IAM' in command
    # Producer/consumer export closure, not just a parameter string assertion.
    producer = synthesize(C4SRCENetwork if srce else C4Network)
    exports = {out['Export']['Name']['Fn::Sub'].replace('${AWS::StackName}', network_name)
               for out in producer['Outputs'].values() if 'Export' in out}
    for project in [r['Properties'] for r in resources.values() if r['Type'] == 'AWS::CodeBuild::Project']:
        imports = list(_import_strings(project['VpcConfig']))
        assert len(imports) == 3
        assert all(imp.replace('${NetworkStackNameParameter}', network_name) in exports for imp in imports)


@pytest.mark.parametrize('status', [1, 2, 130])
def test_validation_is_noninteractive_and_failure_propagates(monkeypatch, status):
    child = Mock(side_effect=subprocess.CalledProcessError(status, ['docker']))
    monkeypatch.setattr(subprocess, 'run', child)
    monkeypatch.setattr(ConfigManager, 'get_aws_creds_dir', lambda: '/offline/credentials with spaces')
    monkeypatch.setattr(C4Client, '_out_templates_mapping_for_mount', lambda: '/offline/templates:/root/templates')
    with pytest.raises(CLIException, match=f'exit status {status}'):
        C4Client.validate_cloudformation_template('/root/templates/a template.yaml')
    args = child.call_args.args[0]
    assert child.call_args.kwargs == {'check': True}
    assert args[:3] == ['docker', 'run', '--rm']
    assert not any(arg in args for arg in ['-it', '-i', '-t', '--tty', '--interactive'])
    assert '/offline/credentials with spaces:/root/.aws' in args
    assert args[-2:] == ['--template-body', 'file:///root/templates/a template.yaml']


def test_failed_validation_stops_before_upload(monkeypatch, synthesis_config):
    stack = Mock()
    stack.print_template.return_value = (Template(), 'test.yaml')
    monkeypatch.setattr(C4Client, 'validate_cloudformation_template',
                        Mock(side_effect=CLIException('validation failed')))
    upload = Mock()
    monkeypatch.setattr(C4Client, 'upload_cloudformation_template', upload)
    monkeypatch.setattr(C4Client, 'resolve_alpha_stack', lambda **kw: stack)
    monkeypatch.setattr(C4Client, 'resolve_4dn_stack', lambda **kw: None)
    args = SimpleNamespace(stack='network', upload_change_set=True, output_file=None,
                           stdout=False, validate=True, view_changes=False)
    with pytest.raises(CLIException, match='validation failed'):
        C4Client.provision_stack(args)
    upload.assert_not_called()


def test_failed_chalice_package_stops_before_changeset(monkeypatch, synthesis_config):
    child = Mock(side_effect=subprocess.CalledProcessError(1, ['docker']))
    monkeypatch.setattr(subprocess, 'run', child)
    with pytest.raises(CLIException, match='exit status 1'):
        C4Client.upload_chalice_package(output_file='offline-package', stack=Mock(), bucket='offline-bucket')
    assert child.call_count == 1
    assert 'package' in child.call_args.args[0]
    assert '-it' not in child.call_args.args[0]
