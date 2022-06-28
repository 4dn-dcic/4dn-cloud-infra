# TODO/dmichaels/2022-06-28: STILL IN PROGRESS 

import boto3
import io
import json
import mock
import os
import re
import sys
import tempfile
from typing import Callable, Optional
from src.auto.setup_remaining_secrets.cli import main
from contextlib import contextmanager
from dcicutils.qa_utils import printed_output as mock_print, MockBoto3, MockBoto3SecretsManager, MockBoto3Session, MockBoto3Sts
from src.auto.setup_remaining_secrets.defs import GacSecretName, RdsSecretName
from src.auto.utils import aws_context
from src.auto.utils import aws
from .testing_utils import rummage_for_print_message, rummage_for_print_message_all


class Input:
    config_file = "config.json"
    custom_dir = "custom"

    gac_secret_name = "C4DatastoreCgapUnitTestApplicationConfiguration"
    rds_secret_name = "C4DatastoreCgapUnitTestRDSSecret"

    aws_credentials_name = "cgap-unit-test"
    aws_credentials_dir = os.path.join(custom_dir, "aws_creds")
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_account_number = "1234567890"
    aws_region = "us-west-2"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"
    aws_iam_users = ["ts.eliot", "j.alfred.prufrock", "c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H"]
    aws_iam_roles = [f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
                     f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
                     f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K"]
    aws_kms_key = "AWS-KMS-KEY-FOR-TESTING"

    elasticsearch_name = f"es-{aws_credentials_name}"
    elasticsearch_host = "elasticsearch.server.for.testing"
    elasticsearch_port = 443
    elasticsearch_https = elasticsearch_port == 443
    elasticsearch_server = f"{elasticsearch_host}:{elasticsearch_port}"
    rds_host = "rds.host.for.testing"
    rds_password = "rds-password-for-testing"


class SecretsExisting:
    ACCOUNT_NUMBER = "some-existing-account-number"
    ENCODED_IDENTITY = "some-existing-encoded-identity"
    ENCODED_ES_SERVER = "some-existing-elasticsearch-server"
    RDS_HOST = "some-existing-rds-host"
    RDS_PASSWORD = "some-existing-rds-password"
    S3_AWS_ACCESS_KEY_ID = "some-existing-s3-aws-access-key-id"
    S3_AWS_SECRET_ACCESS_KEY = "some-existing-s3-aws-secret-access-key"
    ENCODED_S3_ENCRYPT_KEY_ID = "some-existing-encoded-s3-encrypt-key-id"


@contextmanager
def _setup_aws_credentials_dir(aws_access_key_id: str, aws_secret_access_key: str, aws_region: str = None):
    """
    Sets up an AWS credentials directory, in a system temporary directory (for the lifetime
    of this context manager), containing a credentials file with the given AWS access key
    ID and secret access key, and optionally a config file containing the given AWS region.

    :param aws_access_key_id: AWS access key ID
    :param aws_secret_access_key: AWS secret access key
    :param aws_secret_access_key: AWS region name
    :return: Yields full path to the temporary credentials directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        aws_credentials_dir = os.path.join(tmpdir, Input.aws_credentials_dir)
        os.makedirs(aws_credentials_dir)
        aws_credentials_file = os.path.join(aws_credentials_dir, "credentials")
        with io.open(aws_credentials_file, "w") as aws_credentials_fp:
            aws_credentials_fp.write(f"[default]\n")
            aws_credentials_fp.write(f"aws_access_key_id={aws_access_key_id}\n")
            aws_credentials_fp.write(f"aws_secret_access_key={aws_secret_access_key}\n")
        if aws_region:
            aws_config_file = os.path.join(aws_credentials_dir, "config")
            with io.open(aws_config_file, "w") as aws_config_fp:
                aws_config_fp.write(f"[default]\n")
                aws_config_fp.write(f"region={aws_region}\n")
        yield aws_credentials_dir


@contextmanager
def _setup_custom_dir(aws_credentials_name: str, aws_account_number: str, s3_encryption_enabled: bool):
    """
    Sets up a custom config directory, in a system temporary directory (for the lifetime of this context manager),
    containing a config.json file with the given AWS credentials name (e.g. cgap-supertest), and AWS account number.

    :param aws_credentials_name: AWS credentials name (e.g. cgap-superttest).
    :param aws_account_number: AWS account number (e.g. 466564410312)
    :return: Yields full path to the temporary custom directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, Input.custom_dir)
        os.makedirs(custom_dir)
        config_file = os.path.join(custom_dir, Input.config_file)
        with io.open(config_file, "w") as config_file_fp:
            config_json = {}
            config_json["account_number"] = aws_account_number
            config_json["ENCODED_ENV_NAME"] = aws_credentials_name
            if s3_encryption_enabled:
                config_json["s3.bucket.encryption"] = True
            config_file_fp.write(json.dumps(config_json))
        yield custom_dir


def test_setup_remaining_secrets() -> None:
    _test_setup_remaining_secrets(overwrite_existing_secrets=True, s3_encryption_enabled=False)
    _test_setup_remaining_secrets(overwrite_existing_secrets=True, s3_encryption_enabled=True)


def test_setup_remaining_secrets_without_overwriting_existing_secrets() -> None:
    _test_setup_remaining_secrets(overwrite_existing_secrets=False, s3_encryption_enabled=False)
    _test_setup_remaining_secrets(overwrite_existing_secrets=False, s3_encryption_enabled=True)


def _test_setup_remaining_secrets(overwrite_existing_secrets: bool = True, s3_encryption_enabled: bool = True) -> None:

    mocked_boto = MockBoto3()

    mocked_boto.client("iam").put_users_for_testing(Input.aws_iam_users)
    mocked_boto.client("iam").put_roles_for_testing(Input.aws_iam_roles)
    mocked_boto.client("sts").put_caller_identity_for_testing(Input.aws_account_number, Input.aws_user_arn)
    mocked_boto.client("opensearch").put_domain_for_testing(Input.elasticsearch_name, Input.elasticsearch_host, Input.elasticsearch_https)
    mocked_boto.client("kms").put_key_for_testing(Input.aws_kms_key)

    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.rds_secret_name, RdsSecretName.RDS_HOST, Input.rds_host)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.rds_secret_name, RdsSecretName.RDS_PASSWORD, Input.rds_password)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ACCOUNT_NUMBER, SecretsExisting.ACCOUNT_NUMBER)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_IDENTITY, SecretsExisting.ENCODED_IDENTITY)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_ES_SERVER, SecretsExisting.ENCODED_ES_SERVER)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_HOST, SecretsExisting.RDS_HOST)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_PASSWORD, SecretsExisting.RDS_PASSWORD)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_ACCESS_KEY_ID, SecretsExisting.S3_AWS_ACCESS_KEY_ID)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_SECRET_ACCESS_KEY, SecretsExisting.S3_AWS_SECRET_ACCESS_KEY)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_S3_ENCRYPT_KEY_ID, SecretsExisting.ENCODED_S3_ENCRYPT_KEY_ID)

    with _setup_aws_credentials_dir(Input.aws_access_key_id, Input.aws_secret_access_key, Input.aws_region) as aws_credentials_dir, \
         _setup_custom_dir(Input.aws_credentials_name, Input.aws_account_number, s3_encryption_enabled) as custom_dir, \
         mock.patch.object(aws_context, "boto3", mocked_boto), mock.patch.object(aws, "boto3", mocked_boto), \
         mock_print() as mocked_print:

        def find_created_aws_access_key_id_from_output(mocked_print) -> Optional[str]:
            created_aws_access_key_id_output = rummage_for_print_message(mocked_print, ".*Created.*AWS.*Access.*Key.*ID.*" )
            if created_aws_access_key_id_output:
                last_space = created_aws_access_key_id_output.rindex(" ") if " " in created_aws_access_key_id_output else None
                if last_space is not None:
                    created_aws_access_key_id = created_aws_access_key_id_output[last_space + 1:].strip()
                    return created_aws_access_key_id
            return None

        def find_created_aws_secret_access_key_from_output(mocked_print) -> Optional[str]:
            created_aws_secret_access_key_output = rummage_for_print_message(mocked_print, ".*Created.*AWS.*Secret.*Access.*Key.*" )
            if created_aws_secret_access_key_output:
                last_space = created_aws_secret_access_key_output.rindex(" ") if " " in created_aws_secret_access_key_output else None
                if last_space is not None:
                    created_aws_secret_access_key = created_aws_secret_access_key_output[last_space + 1:].strip()
                    return created_aws_secret_access_key
            return None

        def is_confirmation_for_access_key_create(arg) -> bool:
            return re.search(".*sure.*want.*update.*AWS.*secret.*.S3_AWS_ACCESS_KEY_ID.*", arg, re.IGNORECASE)

        def is_confirmation_for_secret_update(arg) -> bool:
            # Are you sure you want to deactivate AWS secret MyTestSecretName.S3_AWS_ACCESS_KEY_ID? [yes/no]:
            return re.search(".*sure.*want.*(create|update|deactivate).*AWS.*secret.*", arg, re.IGNORECASE)

        def mock_input(arg: str):
            if is_confirmation_for_secret_update(arg) and not overwrite_existing_secrets:
                # If this is input for a confirmation to actually update a secret,
                # and this test is for the case where we should  not overwrite any
                # existing secrets then return "no" meaning "do not update secrets".
                return "no"
            return "yes"

        with mock.patch("builtins.input", mock_input) as mocked_input:

            main(["--aws-credentials-dir", aws_credentials_dir, "--custom-dir", custom_dir, "--show"])

            if not overwrite_existing_secrets:

                assert SecretsExisting.ACCOUNT_NUMBER== mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ACCOUNT_NUMBER)
                assert SecretsExisting.ENCODED_IDENTITY == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_IDENTITY)
                assert SecretsExisting.ENCODED_ES_SERVER == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_ES_SERVER)
                assert SecretsExisting.RDS_HOST == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_HOST)
                assert SecretsExisting.RDS_PASSWORD == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_PASSWORD)
                assert SecretsExisting.S3_AWS_ACCESS_KEY_ID == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_ACCESS_KEY_ID)
                assert SecretsExisting.S3_AWS_SECRET_ACCESS_KEY == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_SECRET_ACCESS_KEY)
                assert SecretsExisting.ENCODED_S3_ENCRYPT_KEY_ID == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_S3_ENCRYPT_KEY_ID)

            else:

                assert Input.aws_account_number == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ACCOUNT_NUMBER)
                assert Input.gac_secret_name == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_IDENTITY)
                assert Input.elasticsearch_server == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_ES_SERVER)
                assert Input.rds_host == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_HOST)
                assert Input.rds_password == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.RDS_PASSWORD)
                created_aws_access_key_id = find_created_aws_access_key_id_from_output(mocked_print)
                assert created_aws_access_key_id == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_ACCESS_KEY_ID)
                created_aws_secret_access_key = find_created_aws_secret_access_key_from_output(mocked_print)
                assert created_aws_secret_access_key == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.S3_AWS_SECRET_ACCESS_KEY)
                if s3_encryption_enabled:
                    assert Input.aws_kms_key == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_S3_ENCRYPT_KEY_ID)
                else:
                    assert "DEACTIVATED:" + SecretsExisting.ENCODED_S3_ENCRYPT_KEY_ID == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, GacSecretName.ENCODED_S3_ENCRYPT_KEY_ID)
