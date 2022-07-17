import boto3
import io
import json
import mock
import os
import sys
from typing import Any
from dcicutils import cloudformation_utils
from dcicutils.qa_utils import MockBoto3, MockBoto3Ec2, MockBotoCloudFormationStack
from dcicutils.diff_utils import DiffManager
from src.auto.update_sentieon_security.cli import (
    get_sentieon_compute_node_inbound_security_group_rules,
    get_sentieon_compute_node_outbound_security_group_rules,
    main,
)
from src.auto.utils import aws, aws_context
from .testing_utils import temporary_custom_and_aws_credentials_dirs_for_testing


class TestData:
    aws_credentials_name = "cgap-supertest"
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_region = "us-west-2"
    aws_account_number = "1234567890"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"

    sentieon_ip_address = "123.4.5.6"
    sentieon_stack_name = "c4-sentieon-cgap-supertest-stack"
    sentieon_stack_output_ip_address_key = "SentieonServerIPCgapSupertest"

    security_group_name = "C4NetworkMainApplicationSecurityGroup"
    security_group_id = "sg-0561068965d07c4af"

    stack_outputs = [{
        "OutputKey": sentieon_stack_output_ip_address_key,
        "OutputValue": sentieon_ip_address
    }]
    stacks = [
        MockBotoCloudFormationStack(sentieon_stack_name, mock_outputs=stack_outputs)
    ]


def test_update_sentieon_security() -> None:
    mocked_boto = MockBoto3()
    mocked_boto_ec2 = mocked_boto.client("ec2")
    assert isinstance(mocked_boto_ec2, MockBoto3Ec2)

    mocked_boto_ec2.put_security_group_for_testing(TestData.security_group_name, TestData.security_group_id)
    mocked_boto.client("cloudformation").setup_boto3_mocked_stacks(mocked_boto, mocked_stacks=TestData.stacks)

    with temporary_custom_and_aws_credentials_dirs_for_testing(mocked_boto, TestData) as (custom_dir, aws_credentials_dir), \
         mock.patch("builtins.input") as mocked_input:
        
        aws_object = aws.Aws(aws_credentials_dir)

        # Make sure our mocked security is there.
        assert aws_object.find_security_group_id(TestData.security_group_name) == TestData.security_group_id

        # Answer yes to confirmation.
        mocked_input.return_value = "yes"

        # Call the main module.
        main(["--custom-dir", custom_dir, "--aws-credentials-dir", aws_credentials_dir])

        # Make sure all of the inbound security group rules to define were actually defined.
        inbound_rules_to_define = get_sentieon_compute_node_inbound_security_group_rules()
        inbound_rules_defined = aws_object.get_inbound_security_group_rules(TestData.security_group_id)
        for inbound_rule_to_define in inbound_rules_to_define:
            assert aws_object.find_security_group_rule(inbound_rules_defined,
                                                       inbound_rule_to_define,
                                                       outbound=False) is not None

        # Make sure all of the outbound security group rules to define were actually defined.
        outbound_rules_to_define = get_sentieon_compute_node_outbound_security_group_rules(TestData.sentieon_ip_address)
        outbound_rules_defined = aws_object.get_outbound_security_group_rules(TestData.security_group_id)
        for outbound_rule_to_define in outbound_rules_to_define:
            assert aws_object.find_security_group_rule(outbound_rules_defined,
                                                       outbound_rule_to_define,
                                                       outbound=True) is not None
