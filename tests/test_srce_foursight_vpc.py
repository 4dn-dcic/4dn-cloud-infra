"""
Regression tests for SRCE Foursight Lambda networking across the three-VPC topology.

The contract these tests pin down:

  Every Foursight Lambda in an SRCE deployment runs in the **Application VPC only** -- its ENIs
  attach to Application-VPC private subnets and to the Application-VPC security group, and never
  to the Database or Compute VPC.

The bug they guard against, reproduced end to end from synthesized CloudFormation below:

  * trigger -- all three SRCE network stacks create an ``ApplicationSecurityGroup`` inside their
    *own* IT-provided VPC and export it under an output key matching the resolver pattern
    ``.*Network.*ApplicationSecurityGroup.*`` that ``C4SRCENetworkExports`` inherited from
    ``C4NetworkExports``. ``ConfigManager.find_stack_outputs()`` scans every stack in the account
    and keys on ``OutputKey``, so it returned three security groups from three different VPCs.
  * masking condition -- ``foursight_core.deploy.Deploy.build_config()`` gates on
    ``if security_group_ids:``. An empty resolution therefore wrote *no* ``VpcConfig`` keys at all
    and left whatever stale ``security_group_ids`` were already in the chalice config in place, so
    the resolver's real breakage surfaced first as an absent security group.
  * symptom -- once real IDs were present, CloudFormation rejected every Foursight Lambda with
    ``Security Groups are required to be in the same VPC``, because the subnets came from the
    Application VPC while the security groups spanned all three.

Non-SRCE behavior (``C4NetworkExports``, the proven Foursight path) is asserted unchanged.
"""
import json
import os
import tempfile

import pytest
from unittest import mock

from troposphere import Template

from src.base import ConfigManager
from src.constants import Settings
from src.part import C4Tags, C4Account
from src.parts.network import C4Network, C4NetworkExports
from src.parts.srce_network import (C4SRCENetwork, C4SRCEDBNetwork, C4SRCEComputeNetwork,
                                    C4SRCENetworkExports)
from src.stack import (C4FoursightCGAPStack, C4FoursightFourfrontStack, C4FoursightSMAHTStack,
                       C4FoursightSMAHTSRCEStack)


APP_VPC = 'vpc-0aaaaaaaaaaaaaaa1'
DB_VPC = 'vpc-0bbbbbbbbbbbbbbb2'
COMPUTE_VPC = 'vpc-0ccccccccccccccc3'

APP_PRIVATE_SUBNETS = ['subnet-0app1111111111111', 'subnet-0app2222222222222']
APP_PUBLIC_SUBNETS = ['subnet-0app3333333333333', 'subnet-0app4444444444444']
DB_PRIVATE_SUBNETS = ['subnet-0db11111111111111', 'subnet-0db22222222222222']
COMPUTE_PRIVATE_SUBNETS = ['subnet-0cmp111111111111', 'subnet-0cmp222222222222']

SRCE_CONFIG = {
    Settings.ENV_NAME: 'smaht-srce',
    Settings.VPC_ID: APP_VPC,
    Settings.VPC_CIDR: '10.10.0.0/16',
    Settings.PRIVATE_SUBNETS: APP_PRIVATE_SUBNETS,
    Settings.PUBLIC_SUBNETS: APP_PUBLIC_SUBNETS,
    Settings.DB_VPC_ID: DB_VPC,
    Settings.DB_VPC_CIDR: '10.20.0.0/16',
    Settings.DB_PRIVATE_SUBNETS: DB_PRIVATE_SUBNETS,
    Settings.COMPUTE_VPC_ID: COMPUTE_VPC,
    Settings.COMPUTE_VPC_CIDR: '10.30.0.0/16',
    Settings.COMPUTE_PRIVATE_SUBNETS: COMPUTE_PRIVATE_SUBNETS,
}

# The loose pattern C4SRCENetworkExports used to inherit from C4NetworkExports.
LOOSE_PATTERN = C4NetworkExports._APPLICATION_SECURITY_GROUP_EXPORT_PATTERN


def srce_config(**overrides):
    cfg = dict(SRCE_CONFIG, **overrides)

    def _get(var, default=None, use_default_if_empty=True):
        return cfg.get(var, default)

    return _get


def synthesize(part_class):
    """ Build one SRCE network stack's CloudFormation template, exactly as `cli provision` would. """
    name = part_class.suggest_stack_name()
    part = part_class(name=name, tags=C4Tags(env='srce', project='smaht', owner='project'),
                      account=C4Account(account_number='123456789012', creds_file='/dev/null'))
    return part.build_template(Template()).to_dict()


def stack_outputs_from(template, sg_id_prefix):
    """ Convert a synthesized template's Outputs into the (OutputKey, OutputValue) shape boto3
        returns for a deployed stack, resolving Refs the way CloudFormation would: a Ref to a
        security group becomes that group's physical id, a Ref to the VPC parameter becomes the
        IT-provided VPC id. """
    outputs = []
    for key, spec in template.get('Outputs', {}).items():
        value = spec['Value']
        if isinstance(value, dict) and 'Ref' in value:
            ref = value['Ref']
            if ref in template.get('Parameters', {}):
                value = template['Parameters'][ref]['Default']
            else:
                value = f'sg-{sg_id_prefix}-{ref}'
        outputs.append({'OutputKey': key, 'OutputValue': value})
    return outputs


def security_group_vpcs(template):
    """ {physical security group id -> VPC id} for one synthesized network stack. """
    result = {}
    for key, spec in template.get('Outputs', {}).items():
        if 'SecurityGroup' not in key:
            continue
        resource = template['Resources'][spec['Value']['Ref']]
        vpc_param = resource['Properties']['VpcId']['Ref']
        result[key] = template['Parameters'][vpc_param]['Default']
    return result


def srce_account(include_standard_network=False, omit_application_stack=False):
    """ Synthesize the SRCE network stacks and return everything a Foursight resolver would see:
        (outputs, {OutputKey -> VPC id}). Optionally also stand up a standard (non-SRCE) network
        stack in the same account, or leave the SRCE Application network stack undeployed. """
    specs = [(C4SRCENetwork, 'app'), (C4SRCEDBNetwork, 'db0'), (C4SRCEComputeNetwork, 'cmp')]
    if omit_application_stack:
        specs = specs[1:]
    outputs, key_to_vpc = [], {}
    for part_class, prefix in specs:
        template = synthesize(part_class)
        stack_outputs = stack_outputs_from(template, prefix)
        sg_vpcs = security_group_vpcs(template)
        for output in stack_outputs:
            if output['OutputKey'] in sg_vpcs:
                key_to_vpc[output['OutputKey']] = sg_vpcs[output['OutputKey']]
        outputs.extend(stack_outputs)
    if include_standard_network:
        outputs.append({'OutputKey': C4Network.suggest_stack_name().logical_id(
            C4NetworkExports.APPLICATION_SECURITY_GROUP), 'OutputValue': 'sg-0standardnetwork1'})
    return outputs, key_to_vpc


def security_group_vpc_map(outputs, key_to_vpc):
    """ {physical security group id -> VPC id} across every synthesized stack in the account. """
    return {o['OutputValue']: key_to_vpc[o['OutputKey']]
            for o in outputs if o['OutputKey'] in key_to_vpc}


def fake_find_stack_outputs(outputs):
    """ Stand-in for ConfigManager.find_stack_outputs with the same OutputKey matching semantics
        (exact string or predicate) and the same account-wide scan across every stack. """
    def _find(key_or_pred, value_only=False):
        results = {}
        for output in outputs:
            key = output['OutputKey']
            if key_or_pred(key) if callable(key_or_pred) else key_or_pred == key:
                results[key] = output['OutputValue']
        return list(results.values()) if value_only else results

    return _find


# ---------------------------------------------------------------------------------------------
# The evidence: three stacks, three VPCs, one output-key pattern.
# ---------------------------------------------------------------------------------------------

def test_each_srce_network_stack_owns_a_security_group_in_a_different_vpc():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        vpcs = {}
        for part_class in (C4SRCENetwork, C4SRCEDBNetwork, C4SRCEComputeNetwork):
            template = synthesize(part_class)
            for key, vpc in security_group_vpcs(template).items():
                if key.endswith(C4NetworkExports.APPLICATION_SECURITY_GROUP):
                    vpcs[part_class.__name__] = vpc
    assert vpcs == {
        'C4SRCENetwork': APP_VPC,
        'C4SRCEDBNetwork': DB_VPC,
        'C4SRCEComputeNetwork': COMPUTE_VPC,
    }


def test_loose_export_pattern_still_matches_all_three_vpcs():
    """ The originating trigger. This documents *why* the resolver may not go back to the
        inherited regex: it is genuinely ambiguous across the SRCE three-VPC topology. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        outputs, key_to_vpc = srce_account()
    matched = [o['OutputKey'] for o in outputs if LOOSE_PATTERN.match(o['OutputKey'])]
    assert len(matched) == 3, matched
    assert {key_to_vpc[k] for k in matched} == {APP_VPC, DB_VPC, COMPUTE_VPC}


def test_application_security_group_output_key_is_unique_to_the_application_stack():
    wanted = C4SRCENetworkExports.application_security_group_output_key()
    others = [cls.suggest_stack_name().logical_id(C4NetworkExports.APPLICATION_SECURITY_GROUP)
              for cls in (C4SRCEDBNetwork, C4SRCEComputeNetwork)]
    assert wanted == C4SRCENetwork.suggest_stack_name().logical_id(
        C4NetworkExports.APPLICATION_SECURITY_GROUP)
    assert wanted not in others


# ---------------------------------------------------------------------------------------------
# The fix: security groups resolve to the Application VPC and nothing else.
# ---------------------------------------------------------------------------------------------

def test_get_security_ids_resolves_only_the_application_vpc():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        outputs, key_to_vpc = srce_account()
        with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
            security_ids = C4SRCENetworkExports.get_security_ids()

    vpc_of = security_group_vpc_map(outputs, key_to_vpc)
    # Every security group in the account, for contrast: three, spanning all three VPCs.
    assert set(vpc_of.values()) == {APP_VPC, DB_VPC, COMPUTE_VPC}
    assert len(security_ids) == 1
    assert {vpc_of[sg] for sg in security_ids} == {APP_VPC}


def test_get_security_ids_ignores_a_standard_network_stack_in_the_same_account():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        outputs, _ = srce_account(include_standard_network=True)
        with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
            security_ids = C4SRCENetworkExports.get_security_ids()
    assert security_ids == [next(o['OutputValue'] for o in outputs
                                 if o['OutputKey'] ==
                                 C4SRCENetworkExports.application_security_group_output_key())]
    assert 'sg-0standardnetwork1' not in security_ids


def test_get_security_ids_raises_instead_of_returning_empty():
    """ Removes the masking condition: build_config()'s `if security_group_ids:` gate silently
        keeps a stale VpcConfig when the resolver comes back empty. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        outputs, _ = srce_account(omit_application_stack=True)
        with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
            with pytest.raises(RuntimeError) as exc:
                C4SRCENetworkExports.get_security_ids()
    assert C4SRCENetwork.suggest_stack_name().stack_name in str(exc.value)


# ---------------------------------------------------------------------------------------------
# The fix: subnets cannot diverge across the three SRCE VPCs.
# ---------------------------------------------------------------------------------------------

def test_get_subnet_ids_are_application_vpc_private_subnets_only():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        subnet_ids = C4SRCENetworkExports.get_subnet_ids()
    assert subnet_ids == APP_PRIVATE_SUBNETS
    assert not set(subnet_ids) & set(DB_PRIVATE_SUBNETS)
    assert not set(subnet_ids) & set(COMPUTE_PRIVATE_SUBNETS)


@pytest.mark.parametrize('setting_key, borrowed', [
    (Settings.DB_PRIVATE_SUBNETS, DB_PRIVATE_SUBNETS[0]),
    (Settings.COMPUTE_PRIVATE_SUBNETS, COMPUTE_PRIVATE_SUBNETS[0]),
])
def test_get_subnet_ids_rejects_a_subnet_shared_with_another_srce_vpc(setting_key, borrowed):
    config = srce_config(**{Settings.PRIVATE_SUBNETS: APP_PRIVATE_SUBNETS + [borrowed]})
    with mock.patch.object(ConfigManager, 'get_config_setting', config):
        with pytest.raises(RuntimeError) as exc:
            C4SRCENetworkExports.get_subnet_ids()
    assert setting_key in str(exc.value)
    assert borrowed in str(exc.value)


# ---------------------------------------------------------------------------------------------
# End to end: the chalice config every Foursight Lambda's VpcConfig is built from.
# ---------------------------------------------------------------------------------------------

def build_chalice_config(package_deploy_class, security_ids, subnet_ids):
    """ Run the vendored Deploy.build_config() for real and return the chalice config it writes.
        Only the poetry-export subprocess and the output path are stubbed. """
    with tempfile.TemporaryDirectory() as tmpdir:
        config_path = os.path.join(tmpdir, 'config.json')
        with mock.patch('foursight_core.deploy.subprocess_call', return_value=0), \
                mock.patch.object(package_deploy_class, 'get_config_filepath',
                                  classmethod(lambda cls: config_path)):
            package_deploy_class.build_config(
                'prod', identity='C4AppConfigFoursightSmahtSrce', stack_name='c4-foursight-srce-stack',
                trial_creds={'S3_ENCRYPT_KEY': 'x'}, trial_global_env_bucket=True,
                global_env_bucket='smaht-srce-foursight-envs',
                security_group_ids=security_ids, subnet_ids=subnet_ids, is_foursight_smaht=True)
        with open(config_path) as fp:
            return json.load(fp)


def test_foursight_srce_chalice_config_pins_every_lambda_to_the_application_vpc():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        outputs, key_to_vpc = srce_account()
        with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
            security_ids = C4SRCENetworkExports.get_security_ids()
            subnet_ids = C4SRCENetworkExports.get_subnet_ids()

    value_to_vpc = security_group_vpc_map(outputs, key_to_vpc)
    config = build_chalice_config(C4FoursightSMAHTSRCEStack.PackageDeploy, security_ids, subnet_ids)

    # chalice applies each stage's security_group_ids/subnet_ids to the VpcConfig of *every*
    # Lambda function it generates, so asserting on the stages covers all of them.
    assert set(config['stages']) == {'dev', 'prod'}
    for stage_name, stage in config['stages'].items():
        assert stage['security_group_ids'], stage_name
        assert stage['subnet_ids'], stage_name
        assert {value_to_vpc[sg] for sg in stage['security_group_ids']} == {APP_VPC}, stage_name
        assert stage['subnet_ids'] == APP_PRIVATE_SUBNETS, stage_name
        assert not set(stage['subnet_ids']) & set(DB_PRIVATE_SUBNETS + COMPUTE_PRIVATE_SUBNETS)


def test_foursight_variants_do_not_share_one_mutable_chalice_stage_config():
    """ dict(CONFIG_BASE, app_name=...) is a shallow copy: without a deep copy every Foursight
        variant shares one 'stages' dict, and build_config() mutates it -- so SRCE Application-VPC
        networking would leak into the non-SRCE variants packaged in the same process. """
    variants = [C4FoursightCGAPStack, C4FoursightFourfrontStack,
                C4FoursightSMAHTStack, C4FoursightSMAHTSRCEStack]
    stage_ids = [id(cls.PackageDeploy.CONFIG_BASE['stages']) for cls in variants]
    assert len(set(stage_ids)) == len(variants)

    build_chalice_config(C4FoursightSMAHTSRCEStack.PackageDeploy,
                         ['sg-0srceapplication1'], APP_PRIVATE_SUBNETS)
    for cls in variants:
        if cls is C4FoursightSMAHTSRCEStack:
            continue
        for stage in cls.PackageDeploy.CONFIG_BASE['stages'].values():
            assert 'security_group_ids' not in stage, cls.__name__
            assert 'subnet_ids' not in stage, cls.__name__


# ---------------------------------------------------------------------------------------------
# Non-SRCE behavior is untouched.
# ---------------------------------------------------------------------------------------------

def test_standard_network_exports_keep_their_loose_discovery():
    """ The proven (non-SRCE) Foursight path still finds its Application security group by the
        historical pattern, which tolerates legacy stack names like c4-network-trial-alpha-stack. """
    outputs = [
        {'OutputKey': 'C4NetworkTrialAlphaApplicationSecurityGroup', 'OutputValue': 'sg-0legacy00000001'},
        {'OutputKey': 'C4DatastoreTrialAlphaElasticSearchURL', 'OutputValue': 'https://es.example'},
    ]
    with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
        assert C4NetworkExports.get_security_ids() == ['sg-0legacy00000001']


def test_standard_network_subnet_discovery_unchanged():
    outputs = [
        {'OutputKey': 'C4NetworkTrialAlphaPrivateSubnetA', 'OutputValue': 'subnet-0legacyaaaaaaaa'},
        {'OutputKey': 'C4NetworkTrialAlphaPrivateSubnetB', 'OutputValue': 'subnet-0legacybbbbbbb'},
    ]
    with mock.patch.object(ConfigManager, 'find_stack_outputs', fake_find_stack_outputs(outputs)):
        assert C4NetworkExports.get_subnet_ids() == ['subnet-0legacyaaaaaaaa', 'subnet-0legacybbbbbbb']
