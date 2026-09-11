"""
Regression test for SEC-2: C4SRCENetwork must NOT inherit the standard network stack's
CloudFormation name (c4-network-main-stack). Without its own STACK_NAME_TOKEN it collides with
the standard network stack, so deploying srce-network would update the standard network stack in
place and delete the real VPC/subnet/NAT resources.
"""
from src.parts.network import C4Network
from src.parts.srce_network import C4SRCENetwork, C4SRCEDBNetwork, C4SRCEComputeNetwork


def test_srce_network_has_distinct_stack_name_from_standard_network():
    standard = C4Network.suggest_stack_name().stack_name
    srce = C4SRCENetwork.suggest_stack_name().stack_name
    assert standard != srce, (
        f"srce-network collides with the standard network stack name ({standard}); "
        f"C4SRCENetwork must override STACK_NAME_TOKEN"
    )
    assert srce == 'c4-srce-network-main-stack'


def test_all_srce_network_variants_have_distinct_names():
    names = {
        C4SRCENetwork.suggest_stack_name().stack_name,
        C4SRCEDBNetwork.suggest_stack_name().stack_name,
        C4SRCEComputeNetwork.suggest_stack_name().stack_name,
        C4Network.suggest_stack_name().stack_name,
    }
    # Four classes -> four distinct CloudFormation stack names.
    assert len(names) == 4
