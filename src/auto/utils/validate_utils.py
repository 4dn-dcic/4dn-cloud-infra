import os
from typing import Optional
from dcicutils.misc_utils import PRINT
from .locations import (InfraDirectories, InfraFiles)
from ..utils.misc_utils import (get_json_config_file_value,
                                exit_with_no_action)
from .aws import Aws
from .aws_context import AwsContext


def validate_custom_dir(custom_dir: str) -> (str, str):
    """
    Validates the given custom directory and returns a tuple containing its full path,
    as well as the full path to the JSON config file within this custom directory.
    Exits with error if this value cannot be determined, or if the custom directory
    or JSON config file do not exist.

    :param custom_dir: Explicitly specified path of the custom directory.
    :return: Tuple with full paths of the custom directory and config file.
    """
    custom_dir = InfraDirectories.get_custom_dir(custom_dir)
    if not custom_dir:
        exit_with_no_action("ERROR: Custom directory cannot be determined..")
    if not os.path.isdir(custom_dir):
        exit_with_no_action(f"ERROR: Custom directory does not exist: {custom_dir}")
    config_file = InfraFiles.get_config_file(custom_dir)
    if not os.path.isfile(config_file):
        exit_with_no_action(f"ERROR: Custom config file does not exist: {config_file}")
    return custom_dir, config_file


def validate_aws_credentials_name(aws_credentials_name: str, config_file: str) -> str:
    """
    Validates the given AWS credentials name (e.g. cgap-supertest) and gets and returns
    the value for this if not set. Default if not set is to get from the given JSON
    config file, i.e. from the ENCODED_ENV_NAME key there.
    Exits on error if this value cannot be determined.

    :param aws_credentials_name: Explicitly specified AWS credentials name (e.g. cgap-supertest).
    :param config_file: Full path of the JSON config file.
    :return: AWS credentials name (e.g. cgap-supertest).
    """
    if not aws_credentials_name:
        aws_credentials_name = get_json_config_file_value("ENCODED_ENV_NAME", config_file)
        if not aws_credentials_name:
            exit_with_no_action("ERROR: AWS credentials name cannot be determined.")
    return aws_credentials_name


def validate_aws_credentials_dir(aws_credentials_dir: str, custom_dir: str) -> str:
    """
    Validates the given AWS credentials directory and returns its full path.
    Default if not set is: /full-path-relative-to-current-directory/custom/aws_creds.
    Exits with error if this value cannot be determined.

    :param aws_credentials_dir: Explicitly specified AWS credentials directory (e.g. custom/aws_creds).
    :param custom_dir: Full path of the custom directory (e.g. custom).
    :return: Full path of the AWS credentials directory.
    """
    if not aws_credentials_dir:
        aws_credentials_dir = InfraDirectories.get_custom_aws_creds_dir(custom_dir)
        if not aws_credentials_dir:
            exit_with_no_action(f"ERROR: AWS credentials directory cannot be determined.")
    if aws_credentials_dir:
        aws_credentials_dir = os.path.abspath(os.path.expanduser(aws_credentials_dir))
        if not os.path.isdir(aws_credentials_dir):
            exit_with_no_action(f"ERROR: AWS credentials directory does not exist: {aws_credentials_dir}")
    return aws_credentials_dir


def validate_aws_credentials(credentials_dir: str,
                             access_key_id: str = None,
                             secret_access_key: str = None,
                             default_region: str = None,
                             session_token: str = None,
                             show: bool = False) -> (Aws, AwsContext.Credentials):
    """
    Validates the given AWS credentials which can be either the path to the AWS credentials directory;
    or the AWS access key ID, secret access key, and default region; or the AWS session token.
    Prints the pertinent AWS credentials info, obfuscating senstive data unless show is True.
    Returns a tuple with an Aws object and AwsContext.Credentials containing the credentials.

    :param credentials_dir: Explicitly specified path to AWS credentials directory.
    :param access_key_id: Explicitly specified AWS access key ID.
    :param secret_access_key: Explicitly specified AWS secret access key.
    :param default_region: Explicitly specified AWS default region.
    :param session_token: Explicitly specified AWS session token
    :param show: True to show any displayed sensitive values in plaintext.
    :return: Tuple with an Aws object and AwsContext.Credentials containing the credentials.
    """
    # Get AWS credentials context object.
    aws = Aws(credentials_dir, access_key_id, secret_access_key, default_region, session_token)

    # Verify the AWS credentials context and get the associated AWS credentials number.
    try:
        with aws.establish_credentials(display=True, show=show) as credentials:
            return aws, credentials
    except Exception as e:
        PRINT(e)
        exit_with_no_action("ERROR: Cannot validate AWS credentials.")


def validate_s3_encrypt_key_id(s3_encrypt_key_id: str, config_file: str, aws: Aws) -> Optional[str]:
    """
    Validates the given S3 encryption key ID and returns its value, but only if encryption
    is enabled via the "s3.bucket.encryption" value in the given JSON config file. If not
    set (and it is needed) gets it from AWS via the given Aws object.
    Exits on error if this value (is needed and) cannot be determined.

    :param s3_encrypt_key_id: Explicitly specified S3 encryption key ID.
    :param config_file: Full path to JSON config file.
    :param aws: Aws object.
    :return: S3 encryption key ID or None if S3 encryption no enabled.
    """
    if not s3_encrypt_key_id:
        s3_bucket_encryption = get_json_config_file_value("s3.bucket.encryption", config_file)
        PRINT(f"AWS application S3 bucket encryption enabled: {'Yes' if s3_bucket_encryption else 'No'}")
        if s3_bucket_encryption:
            # Only needed if s3.bucket.encryption is True in the local custom config file.
            customer_managed_kms_keys = aws.get_customer_managed_kms_keys()
            if not customer_managed_kms_keys or len(customer_managed_kms_keys) == 0:
                exit_with_no_action("ERROR: Cannot find a customer managed KMS key in AWS.")
            elif len(customer_managed_kms_keys) > 1:
                PRINT("More than one customer managed KMS key found in AWS:")
                for customer_managed_kms_key in sorted(customer_managed_kms_keys, key=lambda key: key):
                    PRINT(f"- {customer_managed_kms_key}")
                exit_with_no_action("Use --s3-encrypt-key-id to specify specific value.")
            else:
                s3_encrypt_key_id = customer_managed_kms_keys[0]
    if s3_encrypt_key_id:
        PRINT(f"AWS application customer managed KMS (S3 encryption) key ID: {s3_encrypt_key_id}")
    return s3_encrypt_key_id
