# Script for 4dn-cloud-infra to fill out "remaining" secrets in
# global application config after AWS datastore stack setup.
# Ref: https://hms-dbmi.atlassian.net/wiki/spaces/~627943f598eae500689dbdc7/pages/2844229759/Building+and+Deploying+AWS+Infrastructure#Filling-Out-Remaining-Application-Secrets

# The following values need to be filled in for the
# global application config (GAC) secret in AWS:
#
# N.B. For values her which need AWS credentials (aws_access_key_id, aws_secret_access_key),
# we will get these either directly from the command-line, or from the "credentials" file
# and "config" file in either the specified AWS credentials directory, or, by default,
# in the local custom AWS credentials directory, i.e. custom/aws_creds.
#
# N.B. That is, we will NOT rely on the environment of the user invoking this script AT ALL
# for AWS credentials, i.e. neither on the AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and
# AWS_DEFAULT_REGION environment variables, nor on the ~/.aws "credentials" and "config"
# files, nor on the AWS_SHARED_CREDENTIALS_FILE and AWS_CONFIG_FILE environment variables.
# Ref: aws_context.py
#
# - ACCOUNT_NUMBER
#   Get this from "account_number" in custom/config.json, or from
#   boto3.client("sts").get_caller_identity()["Account"] using the
#   specified AWS credentials, and/or both and sanity check each other.
#   Ref: AwsContext.establish_credentials()
#
# - ENCODED_IDENTITY
#   Get this from the identity, i.e. the GAC name,
#   e.g. C4DatastoreCgapSupertestApplicationConfiguration.
#   Ref: Names.application_configuration_secret(aws_credentials_name)
#   TODO: Since this value is generated by the datastore stack provisioning, which also
#   sets up the GAC, why not use the same code to set this at datastore provisioning time?
#
# - ENCODED_ES_SERVER
#   Get this from the endpoint property of the AWS ElasticSearch instance definition
#   named es-{aws_credentials_name} where aws_credentials_name is e.g. cgap-supertest.
#   Ref: Aws.get_elasticsearch_endpoint()
#   TODO: Since this value is generated by the datastore stack provisioning, which also
#   sets up the GAC, why not use the same code to set this at datastore provisioning time?
#   TODO: Actually it looks like this value IS set during datastore stack provisioning time,
#   to e.g. vpc-es-cgap-supertest-asggiedgb6ilmzjuq4hlwgw2w4.us-east-1.es.amazonaws.com,
#   but without the ":443" port suffix, in application_configuration_template() in
#   datastore.py via call to C4DatastoreExports.get_es_url() in datastore.py.
#   TODO: I have a note in my docs that this cannot actualy be set until ES comes online. Hmm.
#
# - RDS_HOSTNAME, RDS_PASSWORD
#   Get these from the "host" and "password" secret key values in the secret name
#   ending in "RDSSecret" in the AWS Secrets Manager.
#   NOTE: The "RDSSecret" secret name is from rds_secret_logical_id in C4Datastore in datastore.py;
#   FACTORED OUT rds_secret_logical_id() from C4Datastore into names.py for this.
#
# - ENCODED_S3_ENCRYPT_KEY_ID
#   Get this from the (one single) customer manager key the AWS Key Management Service (KMS).
#   Only set this if "s3.bucket.encryption" is True in custom/config.json.
#   Ref: Aws.get_customer_managed_kms_keys()
#
# - S3_AWS_ACCESS_KEY_ID, S3_AWS_SECRET_ACCESS_KEY
#   Get these by creating AWS security access key pair for the "federated" IAM user.
#   NOTE: The federated IAM user name (e.g. c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H)
#   is from the AWS IAM user whose name contains "ApplicationS3Federator" which (that string)
#   is referenced/hardcoded in ecs_s3_iam_user() in iam.py;
#   FACTORED OUT ecs_s3_iam_user_logical_id() from C4IAM into name.spy for this.
#   Ref: Aws.create_user_access_key()
#
# - S3_ENCRYPT_KEY
#   This gets set automatically it seems.
#   Though originally this did not seem to be the case.
#   TODO: Get (if not already set) from custom/aws_creds/s3_encrypt_key.txt

import argparse
import os
from typing import Optional
from dcicutils.cloudformation_utils import DEFAULT_ECOSYSTEM
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ...constants import Settings
from ...names import Names
from ..utils.aws import Aws
from ..utils.aws_context import AwsContext
from ..utils.locations import (InfraDirectories, InfraFiles)
from ..utils.misc_utils import (get_json_config_file_value,
                                exit_with_no_action,
                                obfuscate,
                                print_dictionary_as_table,
                                setup_and_action,
                                should_obfuscate)
from ..utils.validate_utils import (validate_aws_credentials,
                                    validate_aws_credentials_dir,
                                    validate_aws_credentials_name,
                                    validate_custom_dir,
                                    validate_s3_encrypt_key_id)


def validate_gac_secret_name(gac_secret_name: str, aws_credentials_name: str) -> str:
    """
    Validates the given global application config secret (aka "identity" aka GAC) and
    returns its value. If not set gets it using the same code that 4dn-cloud-infra code does,
    using the given AWS credentials name. Had to refactor to get this working (see names.py).
    Exits with error if this value cannot be determined.

    :param gac_secret_name: Explicitly specified AWS secret name for the global application config.
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :return: Global application config secret name.
    """
    if not gac_secret_name:
        try:
            gac_secret_name = Names.application_configuration_secret(aws_credentials_name)
        except:
            gac_secret_name = None
        if not gac_secret_name:
            exit_with_no_action(f"ERROR: AWS global application config secret name cannot be determined.")
    return gac_secret_name


def validate_rds_secret_name(rds_secret_name: str, aws_credentials_name: str) -> str:
    """
    Validates the given RDS secret name and returns its value. If not set gets it using
    the same code that 4dn-cloud-infra code does, using the given AWS credentials
    name. Had to refactor to get this working (see names.py).
    Exits with error if this value cannot be determined.

    :param rds_secret_name: Explicitly specified AWS secret name for the RDS secrets.
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :return: RDS secret name as gotten from the main 4dn-cloud-infra code.
    """
    if not rds_secret_name:
        try:
            rds_secret_name = Names.rds_secret_logical_id(aws_credentials_name)
        except:
            rds_secret_name = None
        if not rds_secret_name:
            exit_with_no_action(f"ERROR: AWS RDS application secret name cannot be determined.")
    return rds_secret_name


def validate_account_number(account_number: str, config_file: str, aws_credentials: AwsContext.Credentials) -> str:
    """
    Validates the given AWS account number and returns its value. If not set gets it from the
    given AwsContext.Credentials object. Also gets this value from the given JSON config file.
    Exits with error if these do not match each other, or if the value cannot be determined.

    :param account_number: Explicitly specified AWS account number.
    :param config_file: Full path to the JSON config file.
    :param aws_credentials: AwsContext.Credentials object with valid AWS credentials.
    :return: AWS account number.
    """
    # If account number does not agree with what's in the config file then error out.
    if not account_number:
        account_number = aws_credentials.account_number
        if not account_number:
            exit_with_no_action("ERROR: Account number cannot be determined.")
    if account_number != get_json_config_file_value("account_number", config_file):
        exit_with_no_action(f"ERROR: Account number in your config file ({account_number})"
                            f" does not match AWS ({aws_credentials.account_number}).")
    return account_number


def validate_federated_user_name(federated_user_name: str,
                                 aws_credentials_name: str, config_file: str, aws: Aws) -> str:
    """
    Validates the given AWS federated user IAM name and returns its value. If not set gets it
    the same code that 4dn-cloud-infra code does, using the given AWS credentials and
    the "s3.bucket.ecosystem" value in the given JSON config file.
    Exits with error if this value cannot be determined.

    :param federated_user_name: Explicitly specified AWS federated user IAM name.
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :param config_file: Full path to the JSON config file.
    :param aws: Aws object.
    :return: AWS federated user IAM name.
    """
    if not federated_user_name:
        # Had to refactor out from C4IAM.ecs_s3_iam_user() the Names.ecs_s3_iam_user_logical_id() function.
        ecosystem = get_json_config_file_value(Settings.S3_BUCKET_ECOSYSTEM, config_file, DEFAULT_ECOSYSTEM)
        federated_user_name_pattern = ".*" + Names.ecs_s3_iam_user_logical_id(None, aws_credentials_name, ecosystem)
        federated_user_name = aws.find_iam_user_name(federated_user_name_pattern)
        if not federated_user_name:
            exit_with_no_action(f"ERROR: AWS federated user cannot be determined.")
    PRINT(f"AWS application federated IAM user: {federated_user_name}")
    return federated_user_name


def validate_elasticsearch_endpoint(elasticsearch_server: str, aws_credentials_name: str, aws: Aws) -> str:
    """
    Validates the given ElasticSearch server (host/port) and returns its value. If not set gets
    it from AWS via the given Aws object, and using the given AWS credentials name.
    Exits with error if this value cannot be determined.

    :param elasticsearch_server: Explicitly specified AWS ElasticSearch server (host/port).
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :param aws: Aws object.
    :return: AWS ElasticSearch server (host/port).
    """
    if not elasticsearch_server:
        elasticsearch_server = aws.get_elasticsearch_endpoint(aws_credentials_name)
        if not elasticsearch_server:
            exit_with_no_action(f"ERROR: AWS ElasticSearch server cannot be determined.")
    PRINT(f"AWS application ElasticSearch server: {elasticsearch_server}")
    return elasticsearch_server


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


def validate_s3_access_key_pair(s3_access_key_id: str, s3_secret_access_key: str,
                                federated_user_name: str, aws: Aws, show: bool = False) -> [str, str]:
    """
    Validates the given S3 access key pair and returns their values. If not set then gets these from AWS
    by creating a key pair for the given federated user IAM name (via the given Aws object),
    Either both or neither the given S3 access key ID and secret access key should be specified.
    This is a command-line INTERACTIVE process (via Aws), prompting the user for confirmation.
    Exits on error if these values cannot be determined.

    :param s3_access_key_id: Explicitly specified S3 access key ID.
    :param s3_secret_access_key: Explicitly specified S3 secret access key.
    :param federated_user_name: AWS federated user IAM name.
    :param aws: Aws object.
    :param show: True to show any displayed sensitive values in plaintext.
    """
    try:
        if not s3_access_key_id or not s3_secret_access_key:
            s3_access_key_id, s3_secret_access_key = aws.create_user_access_key(federated_user_name, show)
        return s3_access_key_id, s3_secret_access_key
    except:
        exit_with_no_action("ERROR: S3 access key pair cannot be determined.")


def validate_rds_host_and_password(rds_host: str, rds_password: str,
                                   rds_secret_name: str,
                                   aws: Aws, show: bool = False) -> [str, str]:
    """
    Validates the given RDS host/password and returns their values. If not set then gets these from
    the AWS secrets manager (via the given Aws object), using the given RDS secret name.
    Exits on error if these values cannot be determined.

    :param rds_host: Explicitly specified RDS host.
    :param rds_password: Explicitly specified RDS password.
    :param rds_secret_name: AWS secret name for the RDS secret keys/values.
    :param aws: Aws object.
    :param show: True to show any displayed sensitive values in plaintext.
    """
    if not rds_host:
        rds_host = aws.get_secret_value(rds_secret_name, "host")
        if not rds_host:
            exit_with_no_action("ERROR: RDS host cannot be determined.")
    PRINT(f"AWS application RDS host name: {rds_host}")
    if not rds_password:
        rds_password = aws.get_secret_value(rds_secret_name, "password")
        if not rds_password:
            exit_with_no_action("ERROR: RDS password cannot be determined.")
    PRINT(f"AWS application RDS password: {obfuscate(rds_password, show)}")
    return rds_host, rds_password


def gather_secrets_to_update(args) -> [str, dict, Aws]:
    """
    Gathers and validates the global application config secret (aka "identity" aka GAC) values to update.
    Returns a tuple containing the GAC secret name, secret values to update, and Aws object.
    Exits on error if these values cannot be determined.

    :param args: Command-line arguments values.
    :return: Tuple containing the GAC secret name, secret values to update, and Aws object.
    """

    # Intialize the dictionary secrets to set, which we will collect here.
    secrets_to_update = {}

    # Gather the basic info.
    custom_dir, config_file = validate_custom_dir(args.custom_dir)
    aws_credentials_name = validate_aws_credentials_name(args.aws_credentials_name, config_file)
    aws_credentials_dir = validate_aws_credentials_dir(args.aws_credentials_dir, custom_dir)

    # Get the relevant AWS secret names.
    gac_secret_name = validate_gac_secret_name(args.gac_secret_name, aws_credentials_name)
    rds_secret_name = validate_rds_secret_name(args.rds_secret_name, aws_credentials_name)

    # Print header and basic info.
    PRINT(f"Setting up 4dn-cloud-infra remaining AWS secrets for: {gac_secret_name}")
    PRINT(f"Your custom directory: {custom_dir}")
    PRINT(f"Your custom config file: {config_file}")
    PRINT(f"Your AWS credentials name: {aws_credentials_name}")

    # Validate and print basic AWS credentials info.
    aws, aws_credentials = validate_aws_credentials(aws_credentials_dir,
                                                    args.aws_access_key_id,
                                                    args.aws_secret_access_key,
                                                    args.aws_default_region,
                                                    args.aws_session_token,
                                                    args.show)

    # Print the relevant AWS secret names we are dealing with.
    PRINT(f"AWS global application config secret name: {gac_secret_name}")
    PRINT(f"AWS RDS application config secret name: {rds_secret_name}")

    # Validate/get the account number.
    account_number = validate_account_number(args.aws_account_number, config_file, aws_credentials)
    secrets_to_update["ACCOUNT_NUMBER"] = account_number

    # Validate/get the global application config secret name (aka "identity" aka GAC).
    secrets_to_update["ENCODED_IDENTITY"] = gac_secret_name

    # Validate/get the ElasticSearch server (host/port).
    elasticsearch_server = validate_elasticsearch_endpoint(args.elasticsearch_server, aws_credentials_name, aws)
    secrets_to_update["ENCODED_ES_SERVER"] = elasticsearch_server

    # Validate/get the RDS host/password.
    rds_host, rds_password = validate_rds_host_and_password(args.rds_host, args.rds_password, rds_secret_name, aws)
    secrets_to_update["RDS_HOST"] = rds_host
    secrets_to_update["RDS_PASSWORD"] = rds_password

    # Validate/get the S3 encryption key ID from KMS (iff s3.bucket.encryption is true in config file).
    s3_encrypt_key_id = validate_s3_encrypt_key_id(args.s3_encrypt_key_id, config_file, aws)
    secrets_to_update["ENCODED_S3_ENCRYPT_KEY_ID"] = s3_encrypt_key_id

    # Validate/get the federated user name (needed to create the security access key pair, below).
    federated_user_name = validate_federated_user_name(args.federated_user_name, aws_credentials_name, config_file, aws)

    # Validate/create the security access key/secret pair for the IAM federated user.
    s3_access_key_id, s3_secret_access_key = validate_s3_access_key_pair(args.s3_access_key_id,
                                                                         args.s3_secret_access_key,
                                                                         federated_user_name, aws, args.show)
    secrets_to_update["S3_AWS_ACCESS_KEY_ID"] = s3_access_key_id
    secrets_to_update["S3_AWS_SECRET_ACCESS_KEY"] = s3_secret_access_key

    return gac_secret_name, secrets_to_update, aws


def summarize_secrets_to_update(gac_secret_name: str, secrets_to_update: dict, show: bool = False) -> None:
    """
    Prints a summary of the given AWS global application config secret keys/values to update.

    :param gac_secret_name: Global application config secret name.
    :param secrets_to_update: Dictionary of secret keys/values to update.
    :param show: True to show any displayed sensitive values in plaintext.
    """
    PRINT()
    PRINT(f"Secret keys/values to be set in AWS secrets manager for secret: {gac_secret_name}")

    def secret_key_display_value(key: str, value: str) -> str:
        if value is None:
            return "<no value: deactivate>"
        elif should_obfuscate(key) and not show:
            return obfuscate(value, show)
        else:
            return value
    print_dictionary_as_table("Secret Key Name", "Secret Key Value", secrets_to_update, secret_key_display_value)


def update_secrets(gac_secret_name: str, secrets_to_update: dict, aws: Aws, show: bool = False) -> None:
    """
    Updates the given AWS global application config secret keys/values
    in the AWS secrets manager (via the given Aws object).
    This is a command-line INTERACTIVE process (via Aws), prompting the user for confirmation.

    :param gac_secret_name: Global application config secret name.
    :param secrets_to_update: Dictionary of secret keys/values to update.
    :param aws: Aws object.
    :param show: True to show any displayed sensitive values in plaintext.
    """
    summarize_secrets_to_update(gac_secret_name, secrets_to_update, show)
    if not yes_or_no("Do you want to go ahead and set these secrets in AWS?"):
        exit_with_no_action()
    for secret_key_name, secret_key_value in secrets_to_update.items():
        PRINT()
        aws.update_secret_key_value(gac_secret_name, secret_key_name, secret_key_value, show)


def setup_remaining_secrets(args) -> None:
    """
    Main logical entry point for this script. Gathers, prints, confirms, and update various values
    in the AWS secrets manager for the global application config secret (aka "identity" aka GAC).

    :param args: Command-line arguments values.
    """

    with setup_and_action() as setup_and_action_state:

        # Gather all the secrets to update in the AWS secrets manager for the global application config.
        gac_secret_name, secrets_to_update, aws = gather_secrets_to_update(args)

        setup_and_action_state.note_action_start()

        # Summarize secrets to update, confirm with user, and actually update the secrets.
        update_secrets(gac_secret_name, secrets_to_update, aws, args.show)


def main(override_argv: Optional[list] = None) -> None:
    """
    Main entry point for this script. Parses command-line arguments and calls the main logical entry point.

    :param override_argv: Raw command-line arguments for this invocation.
    """
    argp = argparse.ArgumentParser()
    argp.add_argument("--aws-account-number", required=False,
                      dest="aws_account_number",
                      help="Your AWS account number.")
    argp.add_argument("--aws-access-key-id", required=False,
                      dest="aws_access_key_id",
                      help=f"Your AWS access key ID; also requires --aws-access-secret-key.")
    argp.add_argument("--aws-credentials-dir", required=False,
                      dest="aws_credentials_dir",
                      help=f"Alternate full path to your custom AWS credentials directory.")
    argp.add_argument("--aws-credentials-name", required=False,
                      dest="aws_credentials_name",
                      help=f"The name of your AWS credentials,"
                           f"e.g. <aws-credentials-name> from {InfraDirectories.AWS_DIR}.<aws-credentials-name>.")
    argp.add_argument("--aws-secret-access-key", required=False,
                      dest="aws_secret_access_key",
                      help=f"Your AWS access key ID; also requires --aws-access-key-id.")
    argp.add_argument("--aws-session-token", required=False,
                      dest="aws_session_token",
                      help=f"Your AWS session token; also requires.")
    argp.add_argument("--custom-dir", required=False, default=InfraDirectories.CUSTOM_DIR,
                      dest="custom_dir",
                      help=f"Alternate custom config directory to default: {InfraDirectories.CUSTOM_DIR}.")
    argp.add_argument("--elasticsearch-server", required=False,
                      dest="elasticsearch_server",
                      help="The host name and port of the AWS ElasticSearch server.")
    argp.add_argument("--federated-user", required=False,
                      dest="federated_user_name",
                      help="The name of the application IAM user name used for role federation.")
    argp.add_argument("--identity", required=False,
                      dest="gac_secret_name",
                      help="Global application config secret name (generated by default).")
    argp.add_argument("--no-confirm", required=False,
                      dest="confirm", action="store_false",
                      help="Behave as if all confirmation questions were answered yes.")
    argp.add_argument("--aws-default-region", required=False,
                      dest="aws_default_region",
                      help="The default AWS region.")
    argp.add_argument("--rds-host", required=False,
                      dest="rds_host",
                      help="RDS host name.")
    argp.add_argument("--rds-password", required=False,
                      dest="rds_password",
                      help="RDS password value.")
    argp.add_argument("--rds-secret-name", required=False,
                      dest="rds_secret_name",
                      help="AWS RDS application secret name (generated by default).")
    argp.add_argument("--s3-access-key-id", required=False,
                      dest="s3_access_key_id",
                      help="S3 AWS access key ID.")
    argp.add_argument("--s3-encrypt-key-id", required=False,
                      dest="s3_encrypt_key_id",
                      help="S3 encryption key ID.")
    argp.add_argument("--s3-secret-access-key", required=False,
                      dest="s3_secret_access_key",
                      help="S3 AWS secret access key.")
    argp.add_argument("--show", action="store_true", required=False)
    args = argp.parse_args(override_argv)

    if (args.aws_access_key_id or args.aws_secret_access_key) and \
       not (args.aws_access_key_id and args.aws_secret_access_key):
        exit_with_no_action("Either none or both --aws-access-key-id and --aws-secret-access-key must be specified.")

    if (args.s3_access_key_id or args.s3_secret_access_key) and \
       not (args.s3_access_key_id and args.s3_secret_access_key):
        exit_with_no_action("Either none or both --s3-access-key-id and --s3-secret-access-key must be specified.")

    setup_remaining_secrets(args)


if __name__ == "__main__":
    main()
