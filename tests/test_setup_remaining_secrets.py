import mock
import re
from typing import Optional
from src.auto.setup_remaining_secrets.cli import main
from dcicutils.cloudformation_utils import camelize, DEFAULT_ECOSYSTEM
from dcicutils.qa_utils import printed_output as mock_print, MockBoto3
from src.names import Names
from src.auto.setup_remaining_secrets.defs import GacSecretKeyName, RdsSecretKeyName
from src.auto.utils import aws, aws_context
from .testing_utils import (find_matching_line,
                            temporary_aws_credentials_dir_for_testing,
                            temporary_custom_dir_for_testing)


class TestData:
    aws_credentials_name = "cgap-unit-test"
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_account_number = "1234567890"
    aws_region = "us-west-2"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"
    aws_iam_users = [
        "ts.eliot",
        "j.alfred.prufrock",
        "c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H"
    ]
    aws_iam_roles = [
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
        f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K"
    ]
    aws_kms_key = "AWS-KMS-KEY-FOR-TESTING"

    opensearch_name = f"es-{aws_credentials_name}"
    opensearch_host = "opensearch.server.for.testing"
    opensearch_port = 443
    opensearch_https = opensearch_port == 443
    opensearch_server = f"{opensearch_host}:{opensearch_port}"
    rds_host = "rds.host.for.testing"
    rds_password = "rds-password-for-testing"

    gac_secret_name = f"C4Datastore{camelize(aws_credentials_name)}ApplicationConfiguration"
    rds_secret_name = f"C4Datastore{camelize(aws_credentials_name)}RDSSecret"


class NewSecret:
    ACCOUNT_NUMBER = TestData.aws_account_number
    ENCODED_IDENTITY = TestData.gac_secret_name
    ENCODED_ES_SERVER = TestData.opensearch_server
    RDS_HOSTNAME = TestData.rds_host
    RDS_PASSWORD = TestData.rds_password
    S3_AWS_ACCESS_KEY_ID = None  # dynamically set: see find_created_aws_access_key_id_from_output() below
    S3_AWS_SECRET_ACCESS_KEY = None  # dynamically set: see find_created_aws_secret_access_key_from_output() below
    ENCODED_S3_ENCRYPT_KEY_ID = TestData.aws_kms_key


class OldSecret:
    ACCOUNT_NUMBER = "some-existing-account-number"
    ENCODED_IDENTITY = "some-existing-encoded-identity"
    ENCODED_ES_SERVER = "some-existing-opensearch-server"
    RDS_HOSTNAME = "some-existing-rds-host"
    RDS_PASSWORD = "some-existing-rds-password"
    S3_AWS_ACCESS_KEY_ID = "some-existing-s3-aws-access-key-id"
    S3_AWS_SECRET_ACCESS_KEY = "some-existing-s3-aws-secret-access-key"
    ENCODED_S3_ENCRYPT_KEY_ID = "some-existing-encoded-s3-encrypt-key-id"


def deactivated_secret(existing_secret: str) -> str:
    return "DEACTIVATED:" + existing_secret


def test_setup_remaining_secrets() -> None:
    do_test_setup_remaining_secrets(overwrite_secrets=True, create_access_key_pair=True, encryption_enabled=True)
    do_test_setup_remaining_secrets(overwrite_secrets=True, create_access_key_pair=True, encryption_enabled=False)
    do_test_setup_remaining_secrets(overwrite_secrets=True, create_access_key_pair=False, encryption_enabled=True)
    do_test_setup_remaining_secrets(overwrite_secrets=True, create_access_key_pair=False, encryption_enabled=False)


def test_setup_remaining_secrets_without_overwriting_existing_secrets() -> None:
    do_test_setup_remaining_secrets(overwrite_secrets=False, create_access_key_pair=True, encryption_enabled=True)
    do_test_setup_remaining_secrets(overwrite_secrets=False, create_access_key_pair=True, encryption_enabled=False)
    do_test_setup_remaining_secrets(overwrite_secrets=False, create_access_key_pair=False, encryption_enabled=True)
    do_test_setup_remaining_secrets(overwrite_secrets=False, create_access_key_pair=False, encryption_enabled=False)


def test_get_federated_user_name_pattern() -> None:
    federated_user_name_pattern = Names.ecs_s3_iam_user_logical_id(None,
                                                                   TestData.aws_credentials_name, DEFAULT_ECOSYSTEM)
    assert federated_user_name_pattern == "C4IAMMainApplicationS3Federator"


def do_test_setup_remaining_secrets(overwrite_secrets: bool = True,
                                    create_access_key_pair: bool = True,
                                    encryption_enabled: bool = True) -> None:
    mocked_boto = MockBoto3()

    mocked_boto.client("iam").put_users_for_testing(TestData.aws_iam_users)
    mocked_boto.client("iam").put_roles_for_testing(TestData.aws_iam_roles)
    mocked_boto.client("sts").put_caller_identity_for_testing(TestData.aws_account_number, TestData.aws_user_arn)
    mocked_boto.client("opensearch").put_domain_for_testing(TestData.opensearch_name,
                                                            TestData.opensearch_host,
                                                            TestData.opensearch_https)
    mocked_boto.client("kms").put_key_for_testing(TestData.aws_kms_key)

    mocked_secretsmanager = mocked_boto.client("secretsmanager")
    mocked_secret_put = mocked_secretsmanager.put_secret_key_value_for_testing
    mocked_secret_get = mocked_secretsmanager.get_secret_key_value_for_testing
    mocked_gac_secret_put = lambda key, value: mocked_secret_put(TestData.gac_secret_name, key, value)
    mocked_gac_secret_get = lambda key: mocked_secret_get(TestData.gac_secret_name, key)
    mocked_rds_secret_put = lambda key, value: mocked_secret_put(TestData.rds_secret_name, key, value)

    mocked_rds_secret_put(RdsSecretKeyName.RDS_HOSTNAME, TestData.rds_host)
    mocked_rds_secret_put(RdsSecretKeyName.RDS_PASSWORD, TestData.rds_password)
    mocked_gac_secret_put(GacSecretKeyName.ACCOUNT_NUMBER, OldSecret.ACCOUNT_NUMBER)
    mocked_gac_secret_put(GacSecretKeyName.ENCODED_IDENTITY, OldSecret.ENCODED_IDENTITY)
    mocked_gac_secret_put(GacSecretKeyName.ENCODED_ES_SERVER, OldSecret.ENCODED_ES_SERVER)
    mocked_gac_secret_put(GacSecretKeyName.RDS_HOSTNAME, OldSecret.RDS_HOSTNAME)
    mocked_gac_secret_put(GacSecretKeyName.RDS_PASSWORD, OldSecret.RDS_PASSWORD)
    mocked_gac_secret_put(GacSecretKeyName.S3_AWS_ACCESS_KEY_ID, OldSecret.S3_AWS_ACCESS_KEY_ID)
    mocked_gac_secret_put(GacSecretKeyName.S3_AWS_SECRET_ACCESS_KEY, OldSecret.S3_AWS_SECRET_ACCESS_KEY)
    mocked_gac_secret_put(GacSecretKeyName.ENCODED_S3_ENCRYPT_KEY_ID, OldSecret.ENCODED_S3_ENCRYPT_KEY_ID)

    with temporary_aws_credentials_dir_for_testing(
            TestData.aws_access_key_id,
            TestData.aws_secret_access_key,
            TestData.aws_region) as aws_credentials_dir, \
         temporary_custom_dir_for_testing(
            TestData.aws_credentials_name,
            TestData.aws_account_number,
            encryption_enabled) as custom_dir, \
         mock.patch.object(aws_context, "boto3", mocked_boto), mock.patch.object(aws, "boto3", mocked_boto), \
         mock_print() as mocked_print:

        def find_created_aws_access_key_id_from_output() -> Optional[str]:
            created_value_output = \
                find_matching_line(mocked_print.lines, ".*Created.*AWS.*Access.*Key.*ID.*")
            if created_value_output:
                if " " in created_value_output:
                    last_space = created_value_output.rindex(" ")
                    if last_space is not None:
                        return created_value_output[last_space + 1:].strip()
            return None

        def find_created_aws_secret_access_key_from_output() -> Optional[str]:
            created_value_output = \
                find_matching_line(mocked_print.lines, ".*Created.*AWS.*Secret.*Access.*Key.*")
            if created_value_output:
                if " " in created_value_output:
                    last_space = created_value_output.rindex(" ")
                    if last_space is not None:
                        return created_value_output[last_space + 1:].strip()
            return None

        def find_current_value_of_secret_from_output(secret_key_name: str) -> Optional[str]:
            current_value_output = \
                find_matching_line(mocked_print.lines, f".*Current.*value.*secret.*{secret_key_name}.*")
            if current_value_output:
                if " " in current_value_output:
                    last_space = current_value_output.rindex(" ")
                    if last_space is not None:
                        return current_value_output[last_space + 1:].strip()
            return None

        def is_confirmation_for_access_key_pair_create(arg: str) -> bool:
            return re.search(".*create.*access.*key.*", arg, re.IGNORECASE) is not None

        def is_confirmation_for_secret_update(arg: str) -> bool:
            return re.search(".*sure.*want.*(create|update|deactivate).*AWS.*secret.*", arg, re.IGNORECASE) is not None

        def assert_secret_from_output(secret_key_name: str, secret_key_value) -> None:
            current_value_of_secret_from_output = find_current_value_of_secret_from_output(secret_key_name)
            assert current_value_of_secret_from_output == secret_key_value

        def mocked_yes_or_no(arg: str):
            if is_confirmation_for_secret_update(arg) and not overwrite_secrets:
                # If this is input for a confirmation to actually update an AWS secret,
                # and this test is for the case where we should  not overwrite any
                # existing secrets then return "no" meaning "do not update secrets".
                return False
            if is_confirmation_for_access_key_pair_create(arg) and not create_access_key_pair:
                # If this is input for a confirmation to actually create an AWS security
                # access key pair (for the federated user) and this test is for the case where
                # we should not do this then return "no" meaning "do not create an access key pair".
                return False
            return True

        # def mocked_input(arg: str):
        #     if is_confirmation_for_secret_update(arg) and not overwrite_secrets:
        #         # If this is input for a confirmation to actually update an AWS secret,
        #         # and this test is for the case where we should  not overwrite any
        #         # existing secrets then return "no" meaning "do not update secrets".
        #         return "no"
        #     if is_confirmation_for_access_key_pair_create(arg) and not create_access_key_pair:
        #         # If this is input for a confirmation to actually create an AWS security
        #         # access key pair (for the federated user) and this test is for the case where
        #         # we should not do this then return "no" meaning "do not create an access key pair".
        #         return "no"
        #     return "yes"

        # Mocking input makes import pdb ; pdb.set_trace wig out. Mock yes_or_no instead (2022-12-16/dmichaels).
        # with mock.patch("builtins.input", mocked_input):
        with mock.patch("src.auto.utils.aws.yes_or_no", mocked_yes_or_no), mock.patch("src.auto.setup_remaining_secrets.cli.yes_or_no", mocked_yes_or_no):

            main(["--aws-credentials-dir", aws_credentials_dir, "--custom-dir", custom_dir, "--show"])

            if not overwrite_secrets:

                assert (OldSecret.ACCOUNT_NUMBER
                        == mocked_gac_secret_get(GacSecretKeyName.ACCOUNT_NUMBER))
                assert (OldSecret.ENCODED_IDENTITY
                        == mocked_gac_secret_get(GacSecretKeyName.ENCODED_IDENTITY))
                assert (OldSecret.ENCODED_ES_SERVER
                        == mocked_gac_secret_get(GacSecretKeyName.ENCODED_ES_SERVER))
                assert (OldSecret.RDS_HOSTNAME
                        == mocked_gac_secret_get(GacSecretKeyName.RDS_HOSTNAME))
                assert (OldSecret.RDS_PASSWORD
                        == mocked_gac_secret_get(GacSecretKeyName.RDS_PASSWORD))
                assert (OldSecret.S3_AWS_ACCESS_KEY_ID
                        == mocked_gac_secret_get(GacSecretKeyName.S3_AWS_ACCESS_KEY_ID))
                assert (OldSecret.S3_AWS_SECRET_ACCESS_KEY
                        == mocked_gac_secret_get(GacSecretKeyName.S3_AWS_SECRET_ACCESS_KEY))
                assert (OldSecret.ENCODED_S3_ENCRYPT_KEY_ID
                        == mocked_gac_secret_get(GacSecretKeyName.ENCODED_S3_ENCRYPT_KEY_ID))

            else:

                assert NewSecret.ACCOUNT_NUMBER == mocked_gac_secret_get(GacSecretKeyName.ACCOUNT_NUMBER)
                assert NewSecret.ENCODED_IDENTITY == mocked_gac_secret_get(GacSecretKeyName.ENCODED_IDENTITY)
                assert NewSecret.ENCODED_ES_SERVER == mocked_gac_secret_get(GacSecretKeyName.ENCODED_ES_SERVER)
                assert NewSecret.RDS_HOSTNAME == mocked_gac_secret_get(GacSecretKeyName.RDS_HOSTNAME)
                assert NewSecret.RDS_PASSWORD == mocked_gac_secret_get(GacSecretKeyName.RDS_PASSWORD)

                if not create_access_key_pair:
                    assert deactivated_secret(OldSecret.S3_AWS_ACCESS_KEY_ID) == \
                           mocked_gac_secret_get(GacSecretKeyName.S3_AWS_ACCESS_KEY_ID)
                else:
                    assert find_created_aws_access_key_id_from_output() == \
                           mocked_gac_secret_get(GacSecretKeyName.S3_AWS_ACCESS_KEY_ID)

                if not create_access_key_pair:
                    assert deactivated_secret(OldSecret.S3_AWS_SECRET_ACCESS_KEY) == \
                           mocked_gac_secret_get(GacSecretKeyName.S3_AWS_SECRET_ACCESS_KEY)
                else:
                    assert find_created_aws_secret_access_key_from_output() == \
                           mocked_gac_secret_get(GacSecretKeyName.S3_AWS_SECRET_ACCESS_KEY)

                if encryption_enabled:
                    assert TestData.aws_kms_key == \
                           mocked_gac_secret_get(GacSecretKeyName.ENCODED_S3_ENCRYPT_KEY_ID)
                else:
                    assert deactivated_secret(OldSecret.ENCODED_S3_ENCRYPT_KEY_ID) == \
                           mocked_gac_secret_get(GacSecretKeyName.ENCODED_S3_ENCRYPT_KEY_ID)

            # Make sure we displayed the values of any old/existing secrets correctly.
            assert_secret_from_output(GacSecretKeyName.ACCOUNT_NUMBER, OldSecret.ACCOUNT_NUMBER)
            assert_secret_from_output(GacSecretKeyName.ENCODED_IDENTITY, OldSecret.ENCODED_IDENTITY)
            assert_secret_from_output(GacSecretKeyName.ENCODED_ES_SERVER, OldSecret.ENCODED_ES_SERVER)
            assert_secret_from_output(GacSecretKeyName.RDS_HOSTNAME, OldSecret.RDS_HOSTNAME)
            assert_secret_from_output(GacSecretKeyName.RDS_PASSWORD, OldSecret.RDS_PASSWORD)
            assert_secret_from_output(GacSecretKeyName.S3_AWS_ACCESS_KEY_ID, OldSecret.S3_AWS_ACCESS_KEY_ID)
            assert_secret_from_output(GacSecretKeyName.S3_AWS_SECRET_ACCESS_KEY, OldSecret.S3_AWS_SECRET_ACCESS_KEY)
            assert_secret_from_output(GacSecretKeyName.ENCODED_S3_ENCRYPT_KEY_ID, OldSecret.ENCODED_S3_ENCRYPT_KEY_ID)
