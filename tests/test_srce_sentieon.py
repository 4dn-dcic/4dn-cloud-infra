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

# A complete SRCE configuration: the three IT-provided VPCs, their CIDRs and private subnets, plus
# the two Sentieon inputs an operator supplies. Deliberately has no 'public.subnets': a secure
# enclave's Application VPC is not required to have any, and the stack must deploy without one.
SRCE_CONFIG = dict(matrix.BASE_CONFIG, **{
    'app.kind': 'smaht', 'app.deploy': 'blue/green', 'ENCODED_ENV_NAME': 'smaht-srce',
    'vpc.id': 'vpc-0aaaaaaaaaaaaaaaa', 'vpc.cidr': '10.1.0.0/16',
    'private.subnets': 'subnet-0app1, subnet-0app2',
    'db.vpc.id': 'vpc-0bbbbbbbbbbbbbbbb', 'db.vpc.cidr': '10.2.0.0/16',
    'db.private.subnets': 'subnet-0db1, subnet-0db2',
    'compute.vpc.id': 'vpc-0cccccccccccccccc', 'compute.vpc.cidr': '10.3.0.0/16',
    'compute.private.subnets': 'subnet-0cmp1, subnet-0cmp2',
    Settings.SENTIEON_AMI_ID: AMI_ID,
    Settings.SENTIEON_SSH_KEY: 'test-key',
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


def test_cli_requests_capability_iam_for_this_stack():
    """ The stack creates an instance role, so the CLI must pass --capabilities CAPABILITY_IAM.
        The CLI matches its list as *substrings of the stack name*, and 'c4-srce-sentieon-...'
        contains no 'iam', so the entry is not optional -- without it CloudFormation refuses the
        stack with 'Requires capabilities: [CAPABILITY_IAM]'.
    """
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import c4_alpha_stack_srce_sentieon, c4_alpha_stack_sentieon

    configure()
    account = C4Account(account_number='123456789012', creds_file='/dev/null')
    srce_stack = c4_alpha_stack_srce_sentieon(account)
    assert C4Client.build_capability_param(srce_stack) == \
        f'--capabilities {C4Client.CAPABILITY_IAM}'
    # ... and the standard Sentieon stack, which creates no IAM resource, still does not ask for it
    assert C4Client.build_capability_param(c4_alpha_stack_sentieon(account)) == ''


def test_cli_passes_only_parameters_this_template_declares():
    """ ``aws cloudformation deploy`` refuses the whole deployment -- 'Parameters: [...] do not
        exist in the template' -- when handed an override for a parameter the template does not
        declare. The SRCE branch of the CLI offers every SRCE stack-name override there is, and
        srce-sentieon declares only NetworkStackNameParameter (plus its own SSH key), so the
        overrides have to be filtered against the template or the stack cannot be deployed at all.
    """
    from src.cli import C4Client
    from src.part import C4Account
    from src.stacks.alpha_stacks import c4_alpha_stack_srce_sentieon

    configure()
    stack = c4_alpha_stack_srce_sentieon(C4Account(account_number='123456789012',
                                                   creds_file='/dev/null'))
    declared = C4Client.declared_template_parameters(stack)
    assert 'NetworkStackNameParameter' in declared
    assert 'DBNetworkStackNameParameter' not in declared
    assert 'ComputeNetworkStackNameParameter' not in declared

    flags = C4Client.build_srce_parameter_flags(
        stack=stack,
        available_overrides={'NetworkStackNameParameter': 'c4-srce-network-main-stack',
                             'DBNetworkStackNameParameter': 'c4-srce-network-db-main-stack',
                             'ComputeNetworkStackNameParameter': 'c4-srce-network-compute-main-stack'})
    assert flags == ['--parameter-overrides', '"NetworkStackNameParameter=c4-srce-network-main-stack"']


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


def test_missing_ssh_key_fails_at_synthesis():
    """ Records, rather than changes, the standard stack's behavior for its other required input:
        'sentieon.ssh_key' names a pre-existing EC2 key pair and has no default, so an unset value
        fails offline too. Named here because it is the second key an operator must supply. """
    with pytest.raises(KeyError) as caught:
        synthesize(**{Settings.SENTIEON_SSH_KEY: None})
    assert Settings.SENTIEON_SSH_KEY in str(caught.value)


# ---------------------------------------------------------------------------------------------
# The AMI is configuration
# ---------------------------------------------------------------------------------------------

def test_configured_ami_reaches_the_instance(template):
    assert the_instance(template)['Properties']['ImageId'] == AMI_ID


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
# App VPC placement
# ---------------------------------------------------------------------------------------------

def test_instance_is_in_an_application_vpc_private_subnet(template):
    """ Every network interface sits on an Application VPC *private* subnet export.

        The standard stack imports ``PublicSubnetA``, which srce-network only publishes when
        'public.subnets' is configured -- so the standard placement is both wrong for an enclave
        and undeployable without an optional key.
    """
    interfaces = the_instance(template)['Properties']['NetworkInterfaces']
    assert interfaces
    for interface in interfaces:
        assert interface['SubnetId'] == {
            'Fn::ImportValue': {'Fn::Sub': '${NetworkStackNameParameter}-PrivateSubnetA'}}


def test_no_public_subnet_is_referenced_anywhere(template):
    import json

    assert 'PublicSubnet' not in json.dumps(template)


def test_instance_has_no_public_ip(template):
    for interface in the_instance(template)['Properties']['NetworkInterfaces']:
        assert interface['AssociatePublicIpAddress'] is False


def test_security_group_is_in_the_application_vpc(template):
    groups = resources_of_type(template, 'AWS::EC2::SecurityGroup')
    assert len(groups) == 1
    group = next(iter(groups.values()))
    assert group['Properties']['VpcId'] == {
        'Fn::ImportValue': {'Fn::Sub': '${NetworkStackNameParameter}-VPC'}}


def test_network_imports_resolve_through_the_srce_application_network_exports():
    """ The cross-stack reference is the SRCE Application network stack, so the deployer wires
        NetworkStackNameParameter to c4-srce-network-main-stack rather than the standard one. """
    from src.parts.srce_network import C4SRCENetwork, C4SRCENetworkExports

    configure()
    assert isinstance(C4SRCESentieonSupport.NETWORK_EXPORTS, C4SRCENetworkExports)
    assert C4SRCENetwork.suggest_stack_name().stack_name.startswith('c4-srce-network-')


def test_the_instance_uses_the_configured_application_private_subnet_count():
    """ The subnet export the instance imports is derived from the configured subnets, so a config
        naming a single Application private subnet still resolves (to that one). """
    template = synthesize(**{Settings.PRIVATE_SUBNETS: 'subnet-0onlyone'})
    for interface in the_instance(template)['Properties']['NetworkInterfaces']:
        assert interface['SubnetId'] == {
            'Fn::ImportValue': {'Fn::Sub': '${NetworkStackNameParameter}-PrivateSubnetA'}}


@pytest.mark.parametrize('missing', [None, ''])
def test_missing_private_subnets_fails_loudly_at_synthesis(missing):
    """ An unset 'private.subnets' must raise rather than emit an ImportValue for an export
        srce-network never published. """
    with pytest.raises(RuntimeError) as caught:
        synthesize(**{Settings.PRIVATE_SUBNETS: missing})
    assert Settings.PRIVATE_SUBNETS in str(caught.value)


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


def test_ssh_is_never_world_open(template):
    for rule in ingress_rules(template):
        if rule['Properties'].get('FromPort') == 22:
            assert rule['Properties']['CidrIp'] != '0.0.0.0/0'


def test_ssh_ingress_follows_the_configured_admin_cidr():
    template = synthesize(**{Settings.SENTIEON_ADMIN_CIDR: '192.0.2.0/24'})
    ssh_sources = {rule['Properties']['CidrIp'] for rule in ingress_rules(template)
                   if rule['Properties'].get('FromPort') == 22}
    assert ssh_sources == {'192.0.2.0/24'}


def test_instance_can_reach_the_ssm_endpoints_in_the_app_vpc(template):
    """ With no public IP, Session Manager is the way onto the box, and it speaks HTTPS to the
        Application VPC's SSM interface endpoints. """
    https_targets = {rule['Properties']['CidrIp'] for rule in egress_rules(template)
                     if rule['Properties'].get('FromPort') == 443}
    assert SRCE_CONFIG['vpc.cidr'] in https_targets


def test_instance_can_reach_the_sentieon_license_master(template):
    https_targets = {rule['Properties']['CidrIp'] for rule in egress_rules(template)
                     if rule['Properties'].get('FromPort') == 443}
    assert C4SRCESentieonSupport.SENTIEON_MASTER_CIDR in https_targets


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


def test_the_iam_role_lives_in_this_stack_not_the_shared_iam_stack():
    """ 'iam' is an ecosystem-shared stack the existing deployments consume unchanged; this role
        is scoped to this stack's lifetime and belongs here. """
    import src.stacks.alpha_stacks  # noqa: F401
    from src.base import REGISTERED_STACK_CLASSES

    configure()
    shared_iam = matrix.synthesize(REGISTERED_STACK_CLASSES['alpha']['iam'])
    assert not [key for key in shared_iam['Resources'] if 'Sentieon' in key]


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
