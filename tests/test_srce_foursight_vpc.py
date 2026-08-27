"""
Regression tests for Foursight Lambda networking across the SRCE three-VPC topology.

The contract these tests pin down:

  Every Foursight Lambda in an SRCE deployment runs in the **Application VPC only** -- its ENIs
  attach to Application-VPC private subnets and to the Application-VPC security group, and never
  to the Database or Compute VPC. The SRCE deployment target is ``foursight-srce``; the non-SRCE
  targets (``foursight``, ``foursight-smaht``, ``foursight-production``, ``foursight-development``)
  must refuse to resolve SRCE exports rather than silently mixing VPCs.

The bug they guard against, reproduced end to end from synthesized CloudFormation below:

  * trigger -- the three SRCE network stacks deliberately export the *same* key suffixes
    (``ApplicationSecurityGroup``, ``PrivateSubnetA``/``B``, ...) from three *different* IT-provided
    VPCs, so downstream stacks can ``ImportValue`` them unchanged. Foursight cannot use
    ``ImportValue`` -- chalice bakes literal IDs into ``.chalice/config.json`` -- so it resolves
    them with ``ConfigManager.find_stack_outputs()``, which scans **every stack in the account** and
    matches on ``OutputKey``. Both the SRCE resolver (inherited) and the standard resolver used the
    unanchored patterns ``.*Network.*ApplicationSecurityGroup.*`` / ``.*Network.*PrivateSubnet.*``,
    which match all three SRCE network stacks.
  * masking condition -- ``foursight_core.deploy.Deploy.build_config()`` gates on
    ``if security_group_ids:``. An empty resolution therefore wrote *no* ``VpcConfig`` keys at all
    and left whatever was already in the chalice config in place, so the resolver's real breakage
    surfaced first as an absent security group rather than as a VPC mismatch.
  * symptom -- once real IDs were present, CloudFormation rejected every Foursight Lambda with
    ``Security Groups are required to be in the same VPC``.

The real-world failing command was ``cli provision foursight-smaht --upload-change-set
--foursight-identity ...`` run against an SRCE account: that is the *non-SRCE* stack, and
``--foursight-identity`` sets only the ``IDENTITY`` environment variable -- it does not select SRCE
networking. ``test_non_srce_foursight_*`` below covers exactly that path.
"""
import json
import os
import re
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
STANDARD_VPC = 'vpc-0ddddddddddddddd4'

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

# The unanchored patterns as they stood before this fix. Kept as literals (not read off the live
# classes) so these tests keep documenting the original ambiguity even as the real patterns change.
HISTORICAL_SG_PATTERN = re.compile('.*Network.*ApplicationSecurityGroup.*')
HISTORICAL_SUBNET_PATTERN = re.compile('.*Network.*PrivateSubnet.*')


def srce_config(**overrides):
    cfg = dict(SRCE_CONFIG, **overrides)

    def _get(var, default=None, use_default_if_empty=True):
        return cfg.get(var, default)

    return _get


def synthesize(part_class):
    """ Build one network stack's CloudFormation template, exactly as `cli provision` would. """
    name = part_class.suggest_stack_name()
    part = part_class(name=name, tags=C4Tags(env='srce', project='smaht', owner='project'),
                      account=C4Account(account_number='123456789012', creds_file='/dev/null'))
    return part.build_template(Template()).to_dict()


def stack_outputs_from(template, sg_id_prefix, stack_name, with_export_names=True):
    """ Convert a synthesized template's Outputs into the shape boto3 returns for a deployed stack,
        resolving intrinsics the way CloudFormation would: a Ref to a security group becomes that
        group's physical id, a Ref to the VPC parameter becomes the IT-provided VPC id, and the
        Export's `Fn::Sub` of '${AWS::StackName}-<id>' becomes the real export name.

        `with_export_names=False` models a stack whose outputs carry no export (get_security_ids()
        falls back to the output key there). """
    outputs = []
    for key, spec in template.get('Outputs', {}).items():
        value = spec['Value']
        if isinstance(value, dict) and 'Ref' in value:
            ref = value['Ref']
            if ref in template.get('Parameters', {}):
                value = template['Parameters'][ref]['Default']
            else:
                value = f'sg-{sg_id_prefix}-{ref}'
        output = {'OutputKey': key, 'OutputValue': value}
        export = spec.get('Export', {}).get('Name')
        if with_export_names and isinstance(export, dict) and 'Fn::Sub' in export:
            output['ExportName'] = export['Fn::Sub'].replace('${AWS::StackName}', stack_name)
        outputs.append(output)
    return outputs


def security_group_vpcs(template):
    """ {output key -> VPC id} for the security groups one synthesized network stack exports. """
    result = {}
    for key, spec in template.get('Outputs', {}).items():
        if 'SecurityGroup' not in key:
            continue
        resource = template['Resources'][spec['Value']['Ref']]
        vpc_param = resource['Properties']['VpcId']['Ref']
        result[key] = template['Parameters'][vpc_param]['Default']
    return result


def srce_account(include_standard_network=False, omit_application_stack=False,
                 with_export_names=True):
    """ Synthesize the SRCE network stacks and return what a Foursight resolver would see:
        ({stack name -> [outputs]}, {OutputKey -> VPC id}). Optionally also stand up a standard
        (non-SRCE) network stack, or leave the SRCE Application network stack undeployed. """
    specs = [(C4SRCENetwork, 'app'), (C4SRCEDBNetwork, 'db0'), (C4SRCEComputeNetwork, 'cmp')]
    if omit_application_stack:
        specs = specs[1:]
    stacks, key_to_vpc = {}, {}
    for part_class, prefix in specs:
        template = synthesize(part_class)
        stack_name = part_class.suggest_stack_name().stack_name
        stacks[stack_name] = stack_outputs_from(template, prefix, stack_name,
                                                with_export_names=with_export_names)
        key_to_vpc.update(security_group_vpcs(template))
    if include_standard_network:
        stacks.update(standard_network_account())
        key_to_vpc.update(STANDARD_NETWORK_SG_VPCS)
    return stacks, key_to_vpc


# A standard (non-SRCE) network stack, using the real logical-id prefix C4Network builds, and the
# older un-truncated stack name a long-lived account may still carry.
STANDARD_PREFIX = C4Network.suggest_stack_name().logical_id_prefix
LEGACY_PREFIX = 'C4NetworkTrialAlpha'
STANDARD_NETWORK_SG_VPCS = {f'{STANDARD_PREFIX}{C4NetworkExports.APPLICATION_SECURITY_GROUP}': STANDARD_VPC}


def standard_network_account(prefix=STANDARD_PREFIX, stack_name='c4-network-main-stack'):
    def _output(export_id, value):
        return {'OutputKey': f'{prefix}{export_id}', 'OutputValue': value,
                'ExportName': f'{stack_name}-{export_id}'}

    return {stack_name: [
        _output(C4NetworkExports.APPLICATION_SECURITY_GROUP, 'sg-0standardnetwork1'),
        _output('PrivateSubnetA', 'subnet-0standardaaaaaa'),
        _output('PrivateSubnetB', 'subnet-0standardbbbbbb'),
        _output('VPC', STANDARD_VPC),
    ]}


def all_outputs(stacks):
    return [o for outputs in stacks.values() for o in outputs]


def security_group_vpc_map(stacks, key_to_vpc):
    """ {physical security group id -> VPC id} across every stack in the account. """
    return {o['OutputValue']: key_to_vpc[o['OutputKey']]
            for o in all_outputs(stacks) if o['OutputKey'] in key_to_vpc}


def matches(key_or_pred, key):
    return key_or_pred(key) if callable(key_or_pred) else key_or_pred == key


def fake_find_stack_outputs(stacks):
    """ Stand-in for ConfigManager.find_stack_outputs: same account-wide scan, same OutputKey
        matching semantics (exact string or predicate), same flattening across stacks. """
    def _find(key_or_pred, value_only=False):
        results = {}
        for outputs in stacks.values():
            for output in outputs:
                if matches(key_or_pred, output['OutputKey']):
                    results[output['OutputKey']] = output['OutputValue']
        return list(results.values()) if value_only else results

    return _find


def fake_find_stack_exports(stacks):
    """ Stand-in for ConfigManager.find_stack_exports: matches an output's ExportName (absent on
        outputs that declare no export) rather than its OutputKey. """
    def _find(name_or_pred, value_only=False):
        results = {}
        for outputs in stacks.values():
            for output in outputs:
                export_name = output.get('ExportName')
                if matches(name_or_pred, export_name):
                    results[export_name] = output['OutputValue']
        return list(results.values()) if value_only else results

    return _find


def fake_find_stack_outputs_by_stack(stacks):
    """ Stand-in for ConfigManager.find_stack_outputs_by_stack: matches grouped by owning stack. """
    def _find(key_or_pred):
        results = {}
        for stack_name, outputs in stacks.items():
            for output in outputs:
                if matches(key_or_pred, output['OutputKey']):
                    results.setdefault(stack_name, {})[output['OutputKey']] = output['OutputValue']
        return results

    return _find


def patched(stacks):
    """ Patch both resolver entry points at once, so a test does not have to know which one the
        code under test uses. """
    return mock.patch.multiple(ConfigManager,
                               find_stack_outputs=fake_find_stack_outputs(stacks),
                               find_stack_exports=fake_find_stack_exports(stacks),
                               find_stack_outputs_by_stack=fake_find_stack_outputs_by_stack(stacks))


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


def test_historical_loose_patterns_matched_all_three_srce_vpcs():
    """ The originating trigger, for both security groups and subnets. This documents *why* neither
        resolver may go back to an unanchored pattern. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account()
    keys = [o['OutputKey'] for o in all_outputs(stacks)]

    matched_sgs = [k for k in keys if HISTORICAL_SG_PATTERN.match(k)]
    assert len(matched_sgs) == 3, matched_sgs
    assert {key_to_vpc[k] for k in matched_sgs} == {APP_VPC, DB_VPC, COMPUTE_VPC}

    # Subnets were mixed too -- six private subnets spanning all three VPCs.
    matched_subnets = [k for k in keys if HISTORICAL_SUBNET_PATTERN.match(k)]
    assert len(matched_subnets) == 6, matched_subnets
    assert len({k.split('PrivateSubnet')[0] for k in matched_subnets}) == 3


def test_current_patterns_no_longer_match_any_srce_export():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account()
    for key in (o['OutputKey'] for o in all_outputs(stacks)):
        assert not C4NetworkExports._APPLICATION_SECURITY_GROUP_EXPORT_PATTERN.match(key), key
        assert not C4NetworkExports._PRIVATE_SUBNET_EXPORT_PATTERN.match(key), key


def test_application_security_group_output_key_is_unique_to_the_application_stack():
    wanted = C4SRCENetworkExports.application_security_group_output_key()
    others = [cls.suggest_stack_name().logical_id(C4NetworkExports.APPLICATION_SECURITY_GROUP)
              for cls in (C4SRCEDBNetwork, C4SRCEComputeNetwork)]
    assert wanted == C4SRCENetwork.suggest_stack_name().logical_id(
        C4NetworkExports.APPLICATION_SECURITY_GROUP)
    assert wanted not in others


# ---------------------------------------------------------------------------------------------
# The SRCE Foursight stack: Application VPC only.
# ---------------------------------------------------------------------------------------------

def test_get_security_ids_resolves_only_the_application_vpc():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account()
        with patched(stacks):
            security_ids = C4SRCENetworkExports.get_security_ids()

    vpc_of = security_group_vpc_map(stacks, key_to_vpc)
    # Every security group in the account, for contrast: three, spanning all three VPCs.
    assert set(vpc_of.values()) == {APP_VPC, DB_VPC, COMPUTE_VPC}
    assert len(security_ids) == 1
    assert {vpc_of[sg] for sg in security_ids} == {APP_VPC}


def test_get_security_ids_ignores_a_standard_network_stack_in_the_same_account():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account(include_standard_network=True)
        with patched(stacks):
            security_ids = C4SRCENetworkExports.get_security_ids()
    wanted_key = C4SRCENetworkExports.application_security_group_output_key()
    expected = next(o['OutputValue'] for o in all_outputs(stacks) if o['OutputKey'] == wanted_key)
    assert security_ids == [expected]
    assert 'sg-0standardnetwork1' not in security_ids


def test_foursight_and_ecs_resolve_the_same_export_name():
    """ The earliest divergence between the working ECS path and the failing Foursight path was the
        *identifier*, not the value: ECS resolves the export name via Fn::ImportValue, Foursight
        used the template's logical id. Both now name the same export.

        The ECS side is `ImportValue(Sub('${NetworkStackNameParameter}-<id>'))`, and cli.py sets
        NetworkStackNameParameter to C4SRCENetwork's stack name; the network side is
        `Export(Sub('${AWS::StackName}-<id>'))` on that same stack. """
    app_stack_name = C4SRCENetwork.suggest_stack_name().stack_name

    ecs_side = C4SRCENetworkExports().import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP)
    ecs_template = ecs_side.to_dict()['Fn::ImportValue']['Fn::Sub']
    resolved_by_ecs = ecs_template.replace('${NetworkStackNameParameter}', app_stack_name)

    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        network_template = synthesize(C4SRCENetwork)
    export = network_template['Outputs'][
        C4SRCENetworkExports.application_security_group_output_key()]['Export']['Name']
    published_by_network = export['Fn::Sub'].replace('${AWS::StackName}', app_stack_name)

    assert resolved_by_ecs == published_by_network
    assert C4SRCENetworkExports.application_security_group_export_name() == published_by_network


def test_get_security_ids_matches_by_export_name_not_output_key():
    """ Resolution must survive a stack whose outputs carry export names but whose output keys have
        been re-tokenized (a renamed/re-qualified stack), which is what the export name is for. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account()
        app_stack = C4SRCENetwork.suggest_stack_name().stack_name
        renamed = {name: ([dict(o, OutputKey=f"Renamed{o['OutputKey']}") for o in outputs]
                          if name == app_stack else outputs)
                   for name, outputs in stacks.items()}
        with patched(renamed):
            security_ids = C4SRCENetworkExports.get_security_ids()

    assert len(security_ids) == 1
    assert {security_group_vpc_map(stacks, key_to_vpc)[sg] for sg in security_ids} == {APP_VPC}


def test_get_security_ids_falls_back_to_the_output_key_when_no_export_is_published():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account(with_export_names=False)
        assert all('ExportName' not in o for o in all_outputs(stacks))
        with patched(stacks):
            security_ids = C4SRCENetworkExports.get_security_ids()
    assert {security_group_vpc_map(stacks, key_to_vpc)[sg] for sg in security_ids} == {APP_VPC}


def test_get_security_ids_export_lookup_still_excludes_the_db_and_compute_vpcs():
    """ The DB and Compute stacks export the same suffix under their own stack names, so the export
        name is as discriminating as the output key was meant to be. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account()
    export_names = sorted(o['ExportName'] for o in all_outputs(stacks)
                          if o.get('ExportName', '').endswith(
                              C4NetworkExports.APPLICATION_SECURITY_GROUP))
    assert len(export_names) == 3
    assert C4SRCENetworkExports.application_security_group_export_name() in export_names
    for other in (C4SRCEDBNetwork, C4SRCEComputeNetwork):
        other_export = (f'{other.suggest_stack_name().stack_name}'
                        f'-{C4NetworkExports.APPLICATION_SECURITY_GROUP}')
        assert other_export in export_names
        assert other_export != C4SRCENetworkExports.application_security_group_export_name()


def test_get_security_ids_error_names_both_identifiers_and_lists_what_exists():
    """ If neither lookup resolves, the message must be enough to diagnose the account without
        another round trip -- and must never print security-group values. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account(omit_application_stack=True)
        with patched(stacks):
            with pytest.raises(RuntimeError) as exc:
                C4SRCENetworkExports.get_security_ids()
    message = str(exc.value)
    assert C4SRCENetworkExports.application_security_group_export_name() in message
    assert C4SRCENetworkExports.application_security_group_output_key() in message
    # The DB and Compute exports are still present, and get named as what *does* exist.
    db_export = (f'{C4SRCEDBNetwork.suggest_stack_name().stack_name}'
                 f'-{C4NetworkExports.APPLICATION_SECURITY_GROUP}')
    assert db_export in message
    for output in all_outputs(stacks):
        if str(output['OutputValue']).startswith('sg-'):
            assert output['OutputValue'] not in message


def test_get_security_ids_raises_instead_of_returning_empty():
    """ Removes the masking condition: build_config()'s `if security_group_ids:` gate silently
        keeps a stale VpcConfig when the resolver comes back empty. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account(omit_application_stack=True)
        with patched(stacks):
            with pytest.raises(RuntimeError) as exc:
                C4SRCENetworkExports.get_security_ids()
    assert C4SRCENetwork.suggest_stack_name().stack_name in str(exc.value)


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
# The non-SRCE Foursight stacks: the real-world failing command.
#
#   cli provision foursight-smaht --upload-change-set --foursight-identity <an SRCE identity>
#
# run against an account holding only the three SRCE network stacks.
# ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize('resolver_name', ['get_security_ids', 'get_subnet_ids'])
def test_non_srce_foursight_refuses_an_srce_only_account(resolver_name):
    """ Previously this returned three VPCs' worth of security groups and six subnets across three
        VPCs, and CloudFormation rejected every Lambda. It must now fail at package time, naming
        the target the operator actually wants. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, _ = srce_account()
        with patched(stacks):
            with pytest.raises(RuntimeError) as exc:
                getattr(C4NetworkExports, resolver_name)()
    assert 'foursight-srce' in str(exc.value)


def test_non_srce_foursight_ignores_srce_exports_when_a_standard_network_stack_exists():
    """ With both a standard network stack and the SRCE stacks present, the non-SRCE resolvers see
        only the standard stack -- one VPC, not four. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account(include_standard_network=True)
        with patched(stacks):
            security_ids = C4NetworkExports.get_security_ids()
            subnet_ids = C4NetworkExports.get_subnet_ids()
    assert security_ids == ['sg-0standardnetwork1']
    assert subnet_ids == ['subnet-0standardaaaaaa', 'subnet-0standardbbbbbb']
    assert {security_group_vpc_map(stacks, key_to_vpc)[sg] for sg in security_ids} == {STANDARD_VPC}


@pytest.mark.parametrize('resolver_name', ['get_security_ids', 'get_subnet_ids'])
def test_non_srce_resolvers_refuse_a_match_spanning_two_network_stacks(resolver_name):
    """ Two standard network stacks in one account means two VPCs; the old resolvers flattened them
        into one list. """
    stacks = dict(standard_network_account())
    stacks.update(standard_network_account(
        prefix=LEGACY_PREFIX, stack_name='c4-network-trial-alpha-stack'))
    with patched(stacks):
        with pytest.raises(RuntimeError) as exc:
            getattr(C4NetworkExports, resolver_name)()
    assert 'c4-network-main-stack' in str(exc.value)
    assert 'c4-network-trial-alpha-stack' in str(exc.value)


def test_srce_is_selected_by_the_provision_target_not_by_the_identity_flag():
    """ --foursight-identity only sets the IDENTITY environment variable in the chalice config. The
        network source is bound per stack class, so the *target* is what selects SRCE. The registered
        CLI name tracks STACK_NAME_TOKEN (see the comment on the registration in alpha_stacks.py),
        and it is 'foursight-srce' -- not 'foursight-smaht-srce', and not 'foursight-smaht'. """
    assert type(C4FoursightSMAHTStack.NETWORK_EXPORTS) is C4NetworkExports
    assert type(C4FoursightSMAHTSRCEStack.NETWORK_EXPORTS) is C4SRCENetworkExports

    assert C4FoursightSMAHTSRCEStack.STACK_NAME_TOKEN == 'foursight-srce'
    assert C4FoursightSMAHTStack.STACK_NAME_TOKEN == 'foursight'
    srce_stack_name = C4FoursightSMAHTSRCEStack.suggest_stack_name().stack_name
    assert srce_stack_name != C4FoursightSMAHTStack.suggest_stack_name().stack_name
    assert 'foursight-srce' in srce_stack_name


# ---------------------------------------------------------------------------------------------
# Non-SRCE behavior on a normal account is untouched.
# ---------------------------------------------------------------------------------------------

def test_standard_network_resolvers_work_against_the_real_synthesized_network_stack():
    """ Synthesized, not hand-written: proves the anchored patterns still match what C4Network
        actually emits. """
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        template = synthesize(C4Network)
    stack_name = C4Network.suggest_stack_name().stack_name
    outputs = stack_outputs_from(template, 'std', stack_name)
    outputs = [dict(o, OutputValue=f"value-for-{o['OutputKey']}") for o in outputs]
    with patched({stack_name: outputs}):
        security_ids = C4NetworkExports.get_security_ids()
        subnet_ids = C4NetworkExports.get_subnet_ids()
    assert security_ids == [f'value-for-{STANDARD_PREFIX}{C4NetworkExports.APPLICATION_SECURITY_GROUP}']
    assert subnet_ids and all('PrivateSubnet' in v for v in subnet_ids)


def test_standard_network_resolvers_still_accept_a_legacy_stack_name():
    """ A long-lived account may still carry c4-network-trial-alpha-stack, whose output keys carry
        the qualifier ('C4NetworkTrialAlpha...'). Anchoring on the title token keeps those matching. """
    stacks = standard_network_account(prefix=LEGACY_PREFIX,
                                      stack_name='c4-network-trial-alpha-stack')
    with patched(stacks):
        assert C4NetworkExports.get_security_ids() == ['sg-0standardnetwork1']
        assert C4NetworkExports.get_subnet_ids() == ['subnet-0standardaaaaaa', 'subnet-0standardbbbbbb']


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
                'prod', identity='C4AppConfigSmahtDevSrceFoursight',
                stack_name='c4-foursight-srce-stack',
                trial_creds={'S3_ENCRYPT_KEY': 'x'}, trial_global_env_bucket=True,
                global_env_bucket='smaht-srce-foursight-envs',
                security_group_ids=security_ids, subnet_ids=subnet_ids, is_foursight_smaht=True)
        with open(config_path) as fp:
            return json.load(fp)


def test_foursight_srce_chalice_config_pins_every_lambda_to_the_application_vpc():
    with mock.patch.object(ConfigManager, 'get_config_setting', srce_config()):
        stacks, key_to_vpc = srce_account()
        with patched(stacks):
            security_ids = C4SRCENetworkExports.get_security_ids()
            subnet_ids = C4SRCENetworkExports.get_subnet_ids()

    value_to_vpc = security_group_vpc_map(stacks, key_to_vpc)
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
