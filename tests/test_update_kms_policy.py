import mock
from dcicutils.qa_utils import MockBoto3
from dcicutils.diff_utils import DiffManager
from src.auto.update_kms_policy.cli import main
from src.auto.utils import aws, aws_context
from .testing_utils import setup_aws_credentials_dir, setup_custom_dir


class Input:

    aws_credentials_name = "cgap-unit-test"
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_account_number = "1234567890"
    aws_region = "us-west-2"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"
    aws_kms_key_id = "AWS-KMS-KEY-ID-FOR-TESTING"
    aws_iam_roles = [
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K",
        f"arn:aws:iam::{aws_account_number}:role/c4-NOT-4SIGHT-role-XYZZY"
    ]
    aws_kms_key_policy_roles = [
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_for_ec2",
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_run_task",
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_states",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MonthlyChecksRole-JD70N7QG34KA",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ManualChecksRole-UVPPYE8FXI2X",
        f"arn:aws:iam::{aws_account_number}:user/c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H"
        f"arn:aws:iam::{aws_account_number}:role/c4-iam-main-stack-CGAPECSRole-819710DSF0UV"
    ]
    aws_kms_key_policy_roles_after = [
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_for_ec2",
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_run_task",
        f"arn:aws:iam::{aws_account_number}:role/tibanna_zebra_cgap-supertest_states",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MonthlyChecksRole-JD70N7QG34KA",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ManualChecksRole-UVPPYE8FXI2X",
        f"arn:aws:iam::{aws_account_number}:user/c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H"
        f"arn:aws:iam::{aws_account_number}:role/c4-iam-main-stack-CGAPECSRole-819710DSF0UV"
    ]
    aws_kms_key_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Enable Admin IAM Policies",
                "Effect": "Allow",
                "Principal": {
                    "AWS": "arn:aws:iam::466564410312:user/david.michaels"
                },
                "Action": "kms:*",
                "Resource": "*"
            },
            {
                "Sid": "Allow use of the key",
                "Effect": "Allow",
                "Principal": {
                    "AWS": aws_kms_key_policy_roles
                },
                "Action": ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"],
                "Resource": "*"
            }
        ]
    }


def test_update_kms_policy() -> None:

    mocked_boto = MockBoto3()

    mocked_boto.client("iam").put_roles_for_testing(Input.aws_iam_roles)
    mocked_boto.client("sts").put_caller_identity_for_testing(Input.aws_account_number, Input.aws_user_arn)
    mocked_boto.client("kms").put_key_for_testing(Input.aws_kms_key_id)
    mocked_boto.client("kms").put_key_policy_for_testing(Input.aws_kms_key_id, Input.aws_kms_key_policy)

    with setup_aws_credentials_dir(Input.aws_access_key_id,
                                   Input.aws_secret_access_key, Input.aws_region) as aws_credentials_dir, \
         mock.patch.object(aws_context, "boto3", mocked_boto), mock.patch.object(aws, "boto3", mocked_boto), \
         mock.patch("builtins.input") as mocked_input:

        mocked_input.return_value = "yes"

        aws_object = aws.Aws(aws_credentials_dir)

        kms_key_policy_before = aws_object.get_kms_key_policy(Input.aws_kms_key_id)

        main(["--verbose"])

        kms_key_policy_after = aws_object.get_kms_key_policy(Input.aws_kms_key_id)

        # Get the "after" principals for the KMS key policy in
        # question (i.e. index-1 from Input.aws_kms_key_policy above).
        kms_key_policy_principals_after = kms_key_policy_after["Statement"][1]["Principal"]["AWS"]

        # Make sure the principals for the KMS key policy in question
        # from Input.aws_kms_key_policy above) match what we expect.
        assert sorted(kms_key_policy_principals_after) == sorted(Input.aws_kms_key_policy_roles_after)

        # Disregarding the before/after principals for the KMS key policy
        # in question (i.e. index-1 from Input.aws_kms_key_policy above),
        # make sure that the policies are otherwise the same.
        del kms_key_policy_before["Statement"][1]["Principal"]["AWS"]
        del kms_key_policy_after["Statement"][1]["Principal"]["AWS"]
        assert DiffManager().comparison(kms_key_policy_before, kms_key_policy_after) == []