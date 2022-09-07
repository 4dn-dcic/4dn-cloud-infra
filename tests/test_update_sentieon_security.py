from contextlib import contextmanager
import mock
import pytest
from dcicutils.cloudformation_utils import camelize
from dcicutils.qa_utils import MockBoto3, MockBoto3Ec2, MockBotoCloudFormationStack
from src.auto.update_sentieon_security.cli import (
    get_sentieon_compute_node_inbound_security_group_rules,
    get_sentieon_compute_node_outbound_security_group_rules,
    main,
)
from src.auto.utils import aws as aws_module
from .testing_utils import temporary_custom_and_aws_credentials_dirs_for_testing


class TestData:
    aws_credentials_name = "cgap-supertest-xyzzy"
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_region = "us-west-2"
    aws_account_number = "1234567890"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"

    sentieon_ip_address = "123.4.5.6"
    sentieon_stack_name = f"c4-sentieon-{aws_credentials_name}-stack"
    sentieon_stack_output_ip_address_key = f"SentieonServerIP{camelize(aws_credentials_name)}"

    security_group_name = "C4NetworkMainApplicationSecurityGroup"
    security_group_id = "sg-0561068965d07c4af"

    stack_outputs = [{
        "OutputKey": sentieon_stack_output_ip_address_key,
        "OutputValue": sentieon_ip_address
    }]
    stacks = [
        MockBotoCloudFormationStack(sentieon_stack_name, mock_outputs=stack_outputs)
    ]


@contextmanager
def _basic_setup_for_main():
    mocked_boto = MockBoto3()
    mocked_boto_ec2 = mocked_boto.client("ec2")
    assert isinstance(mocked_boto_ec2, MockBoto3Ec2)

    mocked_boto_ec2.put_security_group_for_testing(TestData.security_group_name, TestData.security_group_id)
    mocked_boto.client("cloudformation").setup_boto3_mocked_stacks(mocked_boto, mocked_stacks=TestData.stacks)

    with temporary_custom_and_aws_credentials_dirs_for_testing(mocked_boto, TestData) as (custom_dir,
                                                                                          aws_credentials_dir), \
        mock.patch("builtins.input") as mocked_input:
        aws = aws_module.Aws(aws_credentials_dir)
        assert aws.find_security_group_id(TestData.security_group_name) == TestData.security_group_id
        yield custom_dir, aws_credentials_dir, aws, mocked_input


def test_update_sentieon_security_yes() -> None:

    with _basic_setup_for_main() as (custom_dir, aws_credentials_dir, aws, mocked_input):

        # Answer yes to confirmation.
        mocked_input.return_value = "yes"

        # Call the main module with confirmation of "yes".
        main(["--custom-dir", custom_dir, "--aws-credentials-dir", aws_credentials_dir])

        # Make sure all of the inbound security group rules to define were actually defined.
        inbound_rules_to_define = get_sentieon_compute_node_inbound_security_group_rules()
        inbound_rules_defined = aws.get_inbound_security_group_rules(TestData.security_group_id)
        assert len(inbound_rules_to_define) == len(inbound_rules_defined)
        for inbound_rule_to_define in inbound_rules_to_define:
            assert aws.find_inbound_security_group_rule(inbound_rules_defined, inbound_rule_to_define) is not None

        # Make sure all of the outbound security group rules to define were actually defined.
        outbound_rules_to_define = get_sentieon_compute_node_outbound_security_group_rules(TestData.sentieon_ip_address)
        outbound_rules_defined = aws.get_outbound_security_group_rules(TestData.security_group_id)
        assert len(outbound_rules_to_define) == len(outbound_rules_defined)
        for outbound_rule_to_define in outbound_rules_to_define:
            assert aws.find_outbound_security_group_rule(outbound_rules_defined, outbound_rule_to_define) is not None


def test_update_sentieon_security_no() -> None:

    with _basic_setup_for_main() as (custom_dir, aws_credentials_dir, aws, mocked_input):

        # Answer no to confirmation.
        mocked_input.return_value = "no"

        # Call the main module with confirmation of "no".
        with pytest.raises(SystemExit):
            main(["--custom-dir", custom_dir, "--aws-credentials-dir", aws_credentials_dir])

        # Make sure nothing got defined.

        inbound_rules_defined = aws.get_inbound_security_group_rules(TestData.security_group_id)
        outbound_rules_defined = aws.get_outbound_security_group_rules(TestData.security_group_id)

        assert not inbound_rules_defined
        assert not outbound_rules_defined
