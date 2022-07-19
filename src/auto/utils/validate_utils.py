import os
from typing import Optional
from dcicutils.misc_utils import PRINT
from .paths import (InfraDirectories, InfraFiles)
from ..utils.misc_utils import (
    get_json_config_file_value,
    exit_with_no_action,
    print_exception,
)
from .aws import Aws


def validate_and_get_custom_dir(custom_dir: str) -> (str, str):
    """
    Validates the given custom directory and returns a tuple containing its full path,
    as well as the full path to the JSON config file within this custom directory.
    Exits with error if this value cannot be determined, or if the custom directory
    or JSON config file do not exist.

    :param custom_dir: Explicitly specified path of the custom config directory.
    :return: Tuple with full paths of the custom directory and config file.
    """
    custom_dir = InfraDirectories.get_custom_dir(custom_dir)
    if not custom_dir:
        exit_with_no_action("ERROR: Custom directory cannot be determined.")
    if not os.path.isdir(custom_dir):
        exit_with_no_action(f"ERROR: Custom directory does not exist: {custom_dir}")
    config_file = InfraFiles.get_config_file(custom_dir)
    if not os.path.isfile(config_file):
        exit_with_no_action(f"ERROR: Custom config file does not exist: {config_file}")
    return custom_dir, config_file


def validate_and_get_aws_credentials_name(aws_credentials_name: str, config_file: str) -> str:
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


def validate_and_get_aws_credentials_dir(aws_credentials_dir: str, custom_dir: str) -> str:
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


def validate_and_get_aws_credentials(credentials_name: str,
                                     credentials_dir: str,
                                     custom_dir: str,
                                     access_key_id: str = None,
                                     secret_access_key: str = None,
                                     region: str = None,
                                     session_token: str = None,
                                     show: bool = False) -> Aws:
    """
    Validates the given AWS credentials which can be either the path to the AWS credentials directory;
    or the AWS access key ID, secret access key, and region; or the AWS session token.
    PRINTS the pertinent AWS credentials info, obfuscating senstive data unless show is True.
    Returns an Aws object with these additional properites set:
    - credentials: AwsContext.Credentials containing credentials which contains:
      - credentials_dir: AWS credentials directory.
      - credentials_dir_symlink_target: AWS credentials directory symlink target if credentials_dir is symlink.
      - access_key_id: AWS Access key ID.
      - secret_access_key: AWS Secret access key.
      - region: AWS region name.
      - account_number: AWS account number.
      - user_arn: AWS account user ARN.
    - credentials_name: AWS credentials name (e.g. cgap-supertest); this is set here not in AwsContext.
    - custom_dir: Path of the custom config directory.
    - custom_config_file: Path of the custom config file.

    :param credentials_name: Explicitly specified AWS credentials name (e.g. cgap-supertest).
    :param credentials_dir: Explicitly specified path to AWS credentials directory.
    :param custom_dir: Explicitly specified path of the custom config directory.
    :param access_key_id: Explicitly specified AWS access key ID.
    :param secret_access_key: Explicitly specified AWS secret access key.
    :param region: Explicitly specified AWS region.
    :param session_token: Explicitly specified AWS session token
    :param show: True to show any displayed sensitive values in plaintext.
    :return: Aws object with credentials property set to AwsContext.Credentials containing credentials.
    """
    custom_dir, custom_config_file = validate_and_get_custom_dir(custom_dir)
    credentials_name = validate_and_get_aws_credentials_name(credentials_name, custom_config_file)
    credentials_dir = validate_and_get_aws_credentials_dir(credentials_dir, custom_dir)

    # Print header and basic info.
    PRINT(f"Your custom directory: {custom_dir}")
    PRINT(f"Your custom config file: {custom_config_file}")
    PRINT(f"Your AWS credentials name: {credentials_name}")

    # Get AWS credentials context object.
    aws = Aws(credentials_dir, access_key_id, secret_access_key, region, session_token)

    # Verify the AWS credentials context and get the associated AWS credentials number.
    try:
        with aws.establish_credentials(display=True, show=show) as credentials:
            if custom_config_file:
                account_number_from_custom_config_file = get_json_config_file_value("account_number", custom_config_file)
                if account_number_from_custom_config_file != credentials.account_number:
                    exit_with_no_action(f"ERROR: AWS account number ({credentials.account_number}) does not match"
                                        f" value ({account_number_from_custom_config_file})"
                                        f" in config file: {custom_config_file}")
            aws.credentials = credentials
            aws.credentials_name = credentials_name
            aws.custom_dir = custom_dir
            aws.custom_config_file = custom_config_file
            return aws
    except Exception as e:
        exit_with_no_action("ERROR: Cannot validate AWS credentials.")
        print_exception(e)


def validate_and_get_s3_encrypt_key_id(s3_encrypt_key_id: str, config_file: str, aws: Aws) -> Optional[str]:
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
