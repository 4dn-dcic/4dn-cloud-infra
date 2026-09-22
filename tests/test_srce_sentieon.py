"""Behavioral contract for the SRCE Sentieon license-server stack.

The standard ``sentieon`` stack is fixed infrastructure and is not exercised here beyond asserting
that the SRCE variant did not change it (``test_standard_sentieon_stack_is_untouched``); whole-stack
parity for it lives in ``tests/test_fixed_stack_parity.py``.

Synthesis goes through ``tests/parity/synthesis_matrix``, which pins ``ConfigManager``'s cached
config and denies all network/AWS access for the process. That matters for more than speed: config
resolves through ``os.environ`` (see AGENTS.md), so a test that did not pin the config would read
the developer's shell.
"""
import pytest

from tests.parity import synthesis_matrix as matrix

from src.base import ConfigManager
from src.constants import Settings
from src.parts.sentieon import C4SentieonSupport
from src.parts.srce_sentieon import C4SRCESentieonSupport


AMI_ID = 'ami-0123456789abcdef0'
AUTHORIZED_DEV_AMI_ID = 'ami-034ba86fa1363855a'

# A complete SRCE configuration: the three IT-provided VPCs, their CIDRs and private subnets, plus
# the Sentieon AMI. Deliberately has no 'public.subnets': a secure enclave's Application VPC does
# not need public subnets for the Sentieon server.
SRCE_CONFIG = dict(matrix.BASE_CONFIG, **{
    'app.kind': 'smaht', 'app.deploy': 'blue/green', 'ENCODED_ENV_NAME': 'smaht-srce',
    'vpc.id': 'vpc-0aaaaaaaaaaaaaaaa', 'vpc.cidr': '10.1.0.0/16',
    'private.subnets': 'subnet-0app1, subnet-0app2',
    'db.vpc.id': 'vpc-0bbbbbbbbbbbbbbbb', 'db.vpc.cidr': '10.2.0.0/16',
    'db.private.subnets': 'subnet-0db1, subnet-0db2',
    'compute.vpc.id': 'vpc-0cccccccccccccccc', 'compute.vpc.cidr': '10.3.0.0/16',
    'compute.private.subnets': 'subnet-0cmp1, subnet-0cmp2',
    Settings.SENTIEON_AMI_ID: AMI_ID,
})


def configure(**overrides):
    """ Pin exactly this configuration for the process, the way synthesis_matrix does. """
    values = dict(SRCE_CONFIG, **overrides)
    matrix.configure(values['app.kind'], values['app.deploy'])
    ConfigManager.singleton()._CACHED_CONFIG = {
        key: (str(val) if val is not None else None) for key, val in values.items()}


def synthesize(**overrides):
    configure(**overrides)
    return matrix.synthesize(C4SRCESentieonSupport)


def resources_of_type(template, resource_type):
    return {key: value for key, value in template['Resources'].items()
            if value['Type'] == resource_type}


def the_instance(template):
    instances = resources_of_type(template, 'AWS::EC2::Instance')
    assert len(instances) == 1, f'expected exactly one EC2 instance, got {sorted(instances)}'
    return next(iter(instances.values()))


@pytest.fixture
def template():
    return synthesize()


# ---------------------------------------------------------------------------------------------
# The stack is registered and deploys from a fresh SRCE configuration
# ---------------------------------------------------------------------------------------------

def test_srce_sentieon_is_registered_as_its_own_stack():
    """ A separate stack, following the srce-* pattern -- not a mode of the standard one. """
    from src.base import REGISTERED_STACK_CLASSES
    import src.stacks.alpha_stacks  # noqa: F401  (importing registers every stack creator)

    assert REGISTERED_STACK_CLASSES['alpha']['srce-sentieon'] is C4SRCESentieonSupport
    assert REGISTERED_STACK_CLASSES['alpha']['sentieon'] is C4SentieonSupport
    assert C4SRCESentieonSupport.suggest_stack_name().stack_name != \
        C4SentieonSupport.suggest_stack_name().stack_name


def test_synthesizes_from_a_fresh_srce_configuration_without_public_subnets(template):
    """ The deployability claim: an SRCE config that supplies the AMI and the ordinary network
        inputs -- and no 'public.subnets' at all -- produces a complete template. """
    assert Settings.PUBLIC_SUBNETS not in SRCE_CONFIG
    assert set(template['Resources']) and set(template['Outputs'])
    assert resources_of_type(template, 'AWS::EC2::SecurityGroup')
    assert resources_of_type(template, 'AWS::IAM::Role')
    assert resources_of_type(template, 'AWS::IAM::InstanceProfile')
    the_instance(template)


def test_cli_requests_named_iam_capability_for_this_stack():
    """ The stack creates IAM resources with explicit names, so the CLI must request
        CAPABILITY_NAMED_IAM.
        The CLI matches its list as *substrings of the stack name*, and 'c4-srce-sentieon-...'
        contains no 'iam', so the entry is not optional -- without it CloudFormation refuses the
        stack with 'Requires capabilities: [CAPABILITY_NAMED_IAM]'.
    """
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import c4_alpha_stack_srce_sentieon, c4_alpha_stack_sentieon

    configure()
    account = C4Account(account_number='123456789012', creds_file='/dev/null')
    srce_stack = c4_alpha_stack_srce_sentieon(account)
    assert C4Client.build_capability_param(srce_stack) == \
        f'--capabilities {C4Client.CAPABILITY_NAMED_IAM}'
    # ... and the standard Sentieon stack, which creates no IAM resource, still does not ask for it
    assert C4Client.build_capability_param(c4_alpha_stack_sentieon(account)) == ''


def test_cli_passes_only_parameters_this_template_declares():
    """ ``aws cloudformation deploy`` refuses the whole deployment -- 'Parameters: [...] do not
        exist in the template' -- when handed an override for a parameter the template does not
        declare. The SRCE branch of the CLI offers every SRCE stack-name override there is, and
        srce-sentieon declares only ComputeNetworkStackNameParameter, so the
        overrides have to be filtered against the template or the stack cannot be deployed at all.
    """
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import c4_alpha_stack_srce_sentieon

    configure()
    stack = c4_alpha_stack_srce_sentieon(C4Account(account_number='123456789012',
                                                   creds_file='/dev/null'))
    declared = C4Client.declared_template_parameters(stack)
    assert 'ComputeNetworkStackNameParameter' in declared
    assert 'NetworkStackNameParameter' not in declared
    assert 'DBNetworkStackNameParameter' not in declared

    flags = C4Client.build_srce_parameter_flags(
        stack=stack,
        available_overrides={'NetworkStackNameParameter': 'c4-srce-network-main-stack',
                             'DBNetworkStackNameParameter': 'c4-srce-network-db-main-stack',
                             'ComputeNetworkStackNameParameter': 'c4-srce-network-compute-main-stack'})
    assert flags == ['--parameter-overrides',
                     '"ComputeNetworkStackNameParameter=c4-srce-network-compute-main-stack"']


def test_cli_parameter_overrides_are_declared_by_every_srce_stack():
    """ Same contract for the sibling SRCE stacks the deploy order runs alongside this one: none
        of them may be offered an override its template does not declare. """
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import create_c4_alpha_stack

    configure()
    account = C4Account(account_number='123456789012', creds_file='/dev/null')
    offered = {'NetworkStackNameParameter': 'net', 'DBNetworkStackNameParameter': 'db',
               'ComputeNetworkStackNameParameter': 'compute', 'ECRStackNameParameter': 'ecr',
               'IAMStackNameParameter': 'iam', 'LoggingStackNameParameter': 'logging',
               'AppConfigStackNameParameter': 'appconfig'}
    for name in ['srce-sentieon', 'srce-datastore', 'srce-redis']:
        stack = create_c4_alpha_stack(name=name, account=account)
        declared = C4Client.declared_template_parameters(stack)
        passed = {flag.strip('"').split('=')[0]
                  for flag in C4Client.build_srce_parameter_flags(stack=stack,
                                                                  available_overrides=offered)
                  if flag != '--parameter-overrides'}
        assert passed <= declared, f'{name} would be passed undeclared {sorted(passed - declared)}'


# ---------------------------------------------------------------------------------------------
# The AMI is configuration
# ---------------------------------------------------------------------------------------------

def test_configured_ami_reaches_the_instance(template):
    assert the_instance(template)['Properties']['ImageId'] == AMI_ID


def test_authorized_dev_ami_survives_synthesis_unchanged():
    template = synthesize(**{Settings.SENTIEON_AMI_ID: AUTHORIZED_DEV_AMI_ID})
    assert the_instance(template)['Properties']['ImageId'] == AUTHORIZED_DEV_AMI_ID


def test_a_different_configured_ami_reaches_the_instance():
    """ Propagation, not a coincidence: a second value must follow the config too, and nothing in
        the template may retain the repository's hardcoded default. """
    other = 'ami-00000000000000abc'
    template = synthesize(**{Settings.SENTIEON_AMI_ID: other})
    assert the_instance(template)['Properties']['ImageId'] == other


def test_the_account_specific_default_ami_is_not_used():
    """ src.constants.EC2Constants.DEFAULT_AMI_IMAGE is an AMI from one specific account. The
        standard stack falls back to it; the SRCE stack must never emit it implicitly. """
    from src.constants import EC2Constants

    template = synthesize()
    assert the_instance(template)['Properties']['ImageId'] != EC2Constants.DEFAULT_AMI_IMAGE


@pytest.mark.parametrize('missing', [None, ''])
def test_missing_ami_fails_loudly_at_synthesis(missing):
    """ No silent fallback and no discovery from ambient AWS state: an unset AMI is an error that
        names the config key, raised offline rather than at deploy time. """
    with pytest.raises(RuntimeError) as caught:
        synthesize(**{Settings.SENTIEON_AMI_ID: missing})
    assert Settings.SENTIEON_AMI_ID in str(caught.value)


@pytest.mark.parametrize('bad', ['not-an-ami', 'ami-', 'ami-zzzzzzzz', 'ami-0123456789abcdef',
                                 'subnet-0123456789abcdef0'])
def test_malformed_ami_fails_loudly_at_synthesis(bad):
    with pytest.raises(RuntimeError) as caught:
        synthesize(**{Settings.SENTIEON_AMI_ID: bad})
    assert Settings.SENTIEON_AMI_ID in str(caught.value)


@pytest.mark.parametrize('good', ['ami-0123456789abcdef0', 'ami-12345678'])
def test_valid_ami_forms_are_accepted(good):
    assert the_instance(synthesize(**{Settings.SENTIEON_AMI_ID: good}))['Properties']['ImageId'] == good


# ---------------------------------------------------------------------------------------------
# Compute VPC placement
# ---------------------------------------------------------------------------------------------

def test_instance_is_in_a_compute_vpc_private_subnet(template):
    """ The license server uses the existing Compute VPC's configured private subnet export. """
    interfaces = the_instance(template)['Properties']['NetworkInterfaces']
    assert interfaces
    for interface in interfaces:
        assert interface['SubnetId'] == {
            'Fn::ImportValue': {'Fn::Sub': '${ComputeNetworkStackNameParameter}-PrivateSubnetA'}}
        assert '${NetworkStackNameParameter}' not in str(interface['SubnetId'])


def test_no_public_subnet_is_referenced_anywhere(template):
    import json

    assert 'PublicSubnet' not in json.dumps(template)


def test_instance_has_no_public_ip(template):
    for interface in the_instance(template)['Properties']['NetworkInterfaces']:
        assert interface['AssociatePublicIpAddress'] is False


def test_security_group_is_in_the_compute_vpc(template):
    groups = resources_of_type(template, 'AWS::EC2::SecurityGroup')
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert group['Properties']['VpcId'] == {
        'Fn::ImportValue': {'Fn::Sub': '${ComputeNetworkStackNameParameter}-VPC'}}
    assert '${NetworkStackNameParameter}' not in str(group['Properties']['VpcId'])


def test_network_imports_resolve_through_the_srce_compute_network_exports():
    """ The deployer wires the reference to the existing SRCE Compute network stack. """
    from src.parts.srce_network import C4SRCEComputeNetwork, C4SRCEComputeNetworkExports

    configure()
    assert isinstance(C4SRCESentieonSupport.NETWORK_EXPORTS, C4SRCEComputeNetworkExports)
    assert C4SRCEComputeNetwork.suggest_stack_name().stack_name.startswith(
        'c4-srce-network-compute-')


def test_the_instance_uses_the_configured_compute_private_subnet_count():
    """ A single configured Compute subnet still resolves to its first export. """
    template = synthesize(**{Settings.COMPUTE_PRIVATE_SUBNETS: 'subnet-0onlyone'})
    for interface in the_instance(template)['Properties']['NetworkInterfaces']:
        assert interface['SubnetId'] == {
            'Fn::ImportValue': {'Fn::Sub': '${ComputeNetworkStackNameParameter}-PrivateSubnetA'}}


@pytest.mark.parametrize('missing', [None, ''])
def test_missing_private_subnets_fails_loudly_at_synthesis(missing):
    """ Missing Compute subnets must not emit an import for an unpublished export. """
    with pytest.raises(RuntimeError) as caught:
        synthesize(**{Settings.COMPUTE_PRIVATE_SUBNETS: missing})
    assert Settings.COMPUTE_PRIVATE_SUBNETS in str(caught.value)


# ---------------------------------------------------------------------------------------------
# Reachability and the operator access path
# ---------------------------------------------------------------------------------------------

def ingress_rules(template):
    return resources_of_type(template, 'AWS::EC2::SecurityGroupIngress').values()


def egress_rules(template):
    return resources_of_type(template, 'AWS::EC2::SecurityGroupEgress').values()


def test_license_port_is_reachable_from_both_the_app_and_compute_vpcs(template):
    license_sources = {rule['Properties']['CidrIp'] for rule in ingress_rules(template)
                       if rule['Properties'].get('FromPort') == 8990}
    assert license_sources == {SRCE_CONFIG['vpc.cidr'], SRCE_CONFIG['compute.vpc.cidr']}


def test_instance_uses_ssm_only_without_ssh_or_public_access(template):
    instance_properties = the_instance(template)['Properties']
    assert 'KeyName' not in instance_properties
    assert not any('SentieonSSHKey' in name for name in template['Parameters'])
    assert not any(rule['Properties'].get('FromPort') == 22 for rule in ingress_rules(template))
    assert not any(rule['Properties'].get('FromPort') == 22 for rule in egress_rules(template))
    assert {rule['Properties'].get('FromPort') for rule in ingress_rules(template)} == {8990}
    assert all(interface['AssociatePublicIpAddress'] is False
               for interface in instance_properties['NetworkInterfaces'])
    assert not resources_of_type(template, 'AWS::EC2::EIP')


def test_instance_has_only_central_https_egress_for_ssm_and_license_master(template):
    """ The existing transit-gateway path carries HTTPS; no other egress is added. """
    rules = list(egress_rules(template))
    assert len(rules) == 1
    assert rules[0]['Properties']['IpProtocol'] == 'tcp'
    assert rules[0]['Properties']['FromPort'] == 443
    assert rules[0]['Properties']['ToPort'] == 443
    assert rules[0]['Properties']['CidrIp'] == '0.0.0.0/0'


def test_instance_does_not_attach_the_ssh_permitting_compute_network_group(template):
    security_groups = resources_of_type(template, 'AWS::EC2::SecurityGroup')
    assert len(security_groups) == 1
    expected_group_ref = {'Ref': next(iter(security_groups))}
    assert all(interface['GroupSet'] == [expected_group_ref]
               for interface in the_instance(template)['Properties']['NetworkInterfaces'])


def test_instance_profile_grants_only_ssm_core(template):
    roles = resources_of_type(template, 'AWS::IAM::Role')
    assert len(roles) == 1
    role = next(iter(roles.values()))
    assert role['Properties']['ManagedPolicyArns'] == \
        ['arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore']
    assert role['Properties']['AssumeRolePolicyDocument']['Statement'][0]['Principal'] == \
        {'Service': 'ec2.amazonaws.com'}


def test_instance_is_attached_to_the_instance_profile(template):
    profiles = resources_of_type(template, 'AWS::IAM::InstanceProfile')
    assert len(profiles) == 1
    profile_id = next(iter(profiles))
    assert the_instance(template)['Properties']['IamInstanceProfile'] == {'Ref': profile_id}
    from src.names import Names
    assert next(iter(resources_of_type(template, 'AWS::IAM::Role').values()))['Properties']['RoleName'] == \
        Names.srce_sentieon_instance_role_name('smaht-srce')
    assert next(iter(resources_of_type(template, 'AWS::IAM::InstanceProfile').values()))[
        'Properties']['InstanceProfileName'] == Names.srce_sentieon_instance_profile_name('smaht-srce')


def test_the_iam_role_lives_in_this_stack_not_the_shared_iam_stack():
    """ 'iam' is an ecosystem-shared stack the existing deployments consume unchanged; this role
        is scoped to this stack's lifetime and belongs here. """
    import src.stacks.alpha_stacks  # noqa: F401
    from src.base import REGISTERED_STACK_CLASSES

    configure()
    shared_iam = matrix.synthesize(REGISTERED_STACK_CLASSES['alpha']['iam'])
    assert not [key for key in shared_iam['Resources'] if 'Sentieon' in key]


def test_srce_dev_role_can_deploy_only_the_srce_sentieon_stack(synthesis_config, synthesize):
    from src.parts.iam import C4IAM
    from src.names import Names

    env_name = 'smaht-dev-srce'
    synthesis_config(kind='smaht', extra={Settings.ENV_NAME: env_name})
    template = synthesize(C4IAM)
    deploy_policies = [policy for role in resources_of_type(template, 'AWS::IAM::Role').values()
                       for policy in role['Properties'].get('Policies', [])
                       if policy['PolicyName'] == f'{env_name}-SRCESentieonStackDeployAccess']
    assert len(deploy_policies) == 1
    deploy_policy = deploy_policies[0]
    statements = deploy_policy['PolicyDocument']['Statement']

    cloudformation = next(statement for statement in statements
                          if 'cloudformation:CreateChangeSet' in statement['Action'])
    assert cloudformation['Resource'] != '*'
    assert Names.srce_sentieon_stack_name_object(env_name).stack_name in str(cloudformation['Resource'])
    assert set(cloudformation['Action']) == {
        'cloudformation:CreateChangeSet', 'cloudformation:DeleteChangeSet',
        'cloudformation:ExecuteChangeSet', 'cloudformation:CreateStack',
        'cloudformation:UpdateStack', 'cloudformation:DeleteStack',
        'cloudformation:ContinueUpdateRollback', 'cloudformation:CancelUpdateStack',
        'cloudformation:RollbackStack',
    }

    role_arn = str(Names.srce_sentieon_instance_role_name(env_name))
    profile_arn = str(Names.srce_sentieon_instance_profile_name(env_name))
    pass_role = next(statement for statement in statements if statement['Action'] == 'iam:PassRole')
    assert role_arn in str(pass_role['Resource'])
    assert 'AWS::AccountId' in str(pass_role['Resource'])
    assert '*' not in str(pass_role['Resource'])
    assert pass_role['Condition'] == {'StringEquals': {'iam:PassedToService': 'ec2.amazonaws.com'}}

    role_permissions = next(statement for statement in statements
                            if 'iam:CreateRole' in statement['Action'])
    profile_permissions = next(statement for statement in statements
                               if 'iam:CreateInstanceProfile' in statement['Action'])
    attach_policy = next(statement for statement in statements
                         if 'iam:AttachRolePolicy' in statement['Action'])
    assert role_arn in str(role_permissions['Resource'])
    assert 'AWS::AccountId' in str(role_permissions['Resource'])
    assert role_arn in str(profile_permissions['Resource'])
    assert profile_arn in str(profile_permissions['Resource'])
    assert role_arn in str(attach_policy['Resource'])
    assert attach_policy['Condition'] == {
        'ArnEquals': {
            'iam:PolicyARN': 'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
        },
    }
    policy_actions = [action for statement in statements
                      for action in (statement['Action'] if isinstance(statement['Action'], list)
                                     else [statement['Action']])]
    assert all(not action.startswith(('ec2:', 'ssm:', 'kms:')) for action in policy_actions)
    assert all(action.startswith(('cloudformation:', 'iam:')) for action in policy_actions)
    assert all(statement['Resource'] != '*' for statement in statements)


@pytest.mark.parametrize('kind,env_name', [
    ('smaht', 'smaht-dev'),
    ('cgap', 'cgap-dev-srce'),
    ('ff', 'fourfront-dev-srce'),
])
def test_sentieon_dev_permissions_are_absent_outside_srce(synthesis_config, synthesize, kind, env_name):
    from src.parts.iam import C4IAM

    synthesis_config(kind=kind, extra={Settings.ENV_NAME: env_name})
    template = synthesize(C4IAM)
    all_policies = [policy for role in resources_of_type(template, 'AWS::IAM::Role').values()
                    for policy in role['Properties'].get('Policies', [])]
    assert not any(policy['PolicyName'].endswith('-SRCESentieonStackDeployAccess')
                   for policy in all_policies)


# ---------------------------------------------------------------------------------------------
# Storage, bootstrap, ordering, output
# ---------------------------------------------------------------------------------------------

def test_root_volume_is_encrypted(template):
    mappings = the_instance(template)['Properties']['BlockDeviceMappings']
    assert mappings
    for mapping in mappings:
        assert mapping['Ebs']['Encrypted'] is True


def test_root_volume_size_is_configurable():
    template = synthesize(**{Settings.SENTIEON_VOLUME_SIZE: 64})
    assert the_instance(template)['Properties']['BlockDeviceMappings'][0]['Ebs']['VolumeSize'] == 64


def test_instance_type_is_configurable():
    assert the_instance(synthesize())['Properties']['InstanceType'] == \
        C4SRCESentieonSupport.DEFAULT_INSTANCE_TYPE
    template = synthesize(**{Settings.SENTIEON_INSTANCE_TYPE: 'm5.large'})
    assert the_instance(template)['Properties']['InstanceType'] == 'm5.large'


def test_bootstrap_brings_up_the_ssm_agent(template):
    lines = the_instance(template)['Properties']['UserData']['Fn::Base64']['Fn::Join'][1]
    assert any('amazon-ssm-agent' in line for line in lines)


def test_instance_waits_for_its_security_group_rules(template):
    """ GroupSet orders the instance after the security group but not after its rules, and the
        bootstrap needs egress the moment the instance boots. """
    instance = the_instance(template)
    rule_ids = {key for key, value in template['Resources'].items()
                if value['Type'].startswith('AWS::EC2::SecurityGroup')
                and value['Type'] != 'AWS::EC2::SecurityGroup'}
    assert set(instance['DependsOn']) == rule_ids


def test_server_ip_output_is_the_private_ip(template):
    outputs = template['Outputs']
    assert len(outputs) == 1
    output = next(iter(outputs.values()))
    assert output['Value']['Fn::GetAtt'][1] == 'PrivateIp'


# ---------------------------------------------------------------------------------------------
# The fixed standard Sentieon stack is untouched
# ---------------------------------------------------------------------------------------------

def test_standard_sentieon_stack_is_untouched():
    """ The standard stack keeps its public-subnet placement, its public IP and its AMI default.

        Not an endorsement of any of those -- it is fixed infrastructure, and the point of putting
        the enclave behaviour in a subclass is that nothing here reaches it.
    """
    import json

    from src.constants import EC2Constants

    configure()
    template = matrix.synthesize(C4SentieonSupport)
    instance = the_instance(template)
    assert instance['Properties']['ImageId'] == EC2Constants.DEFAULT_AMI_IMAGE
    assert 'PublicSubnetA' in json.dumps(instance['Properties']['NetworkInterfaces'])
    assert instance['Properties']['NetworkInterfaces'][0]['AssociatePublicIpAddress'] is True
    assert not resources_of_type(template, 'AWS::IAM::Role')
    assert 'IamInstanceProfile' not in instance['Properties']
