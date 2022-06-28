# Script for 4dn-cloud-infra to update KMS key policy for Foursight.

import argparse
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ..utils.locations import (InfraDirectories)
from ..utils.misc_utils import (get_json_config_file_value,
                                exit_with_no_action)
from ..utils.validate_utils import (validate_aws_credentials,
                                    validate_aws_credentials_dir,
                                    validate_aws_credentials_name,
                                    validate_custom_dir,
                                    validate_s3_encrypt_key_id)


def update_kms_policy(args) -> None:
    """
    Main logical entry point for this script. Gathers, prints, confirms, and updates the KMS policy for Foursight.

    :param args: Command-line arguments values.
    """

    # Gather the basic info.
    custom_dir, config_file = validate_custom_dir(args.custom_dir)
    aws_credentials_name = validate_aws_credentials_name(args.aws_credentials_name, config_file)
    aws_credentials_dir = validate_aws_credentials_dir(args.aws_credentials_dir, custom_dir)

    # Print header and basic info.
    PRINT(f"Updating 4dn-cloud-infra KMS policy for Foursight IAM roles.")
    PRINT(f"Your custom directory: {custom_dir}")
    PRINT(f"Your custom config file: {config_file}")
    PRINT(f"Your AWS credentials name: {aws_credentials_name}")

    # Validate and print basic AWS credentials info.
    aws, aws_credentials = validate_aws_credentials(aws_credentials_dir,
                                                    args.aws_access_key_id,
                                                    args.aws_secret_access_key,
                                                    args.aws_region,
                                                    args.aws_session_token,
                                                    args.show)

    # Validate/get the S3 encryption key ID from KMS (iff s3.bucket.encryption is true in config file).
    kms_key_id = validate_s3_encrypt_key_id(args.s3_encrypt_key_id, config_file, aws)
    if not kms_key_id:
        s3_bucket_encryption = get_json_config_file_value("s3.bucket.encryption", config_file)
        if not s3_bucket_encryption:
            exit_with_no_action("No KMS key found."
                                "And encryption not enabled (via s3.bucket.encryption in config file).")
        else:
            exit_with_no_action("ERROR: No KMS key found.")

    # Get the ARNs for the Foursight roles.
    foursight_role_arn_pattern = ".*foursight.*"
    foursight_role_arns = aws.find_iam_role_arns(foursight_role_arn_pattern)
    if foursight_role_arns and len(foursight_role_arns) > 0:
        if args.verbose:
            PRINT("Foursight AWS IAM role ARNs:")
            for foursight_role_arn in sorted(foursight_role_arns):
                PRINT(f"- {foursight_role_arn}")
    else:
        exit_with_no_action("No Foursight AWS IAM roles found.")

    # Get the KMS policy JSON for the S3 encryption KMS key ID.
    kms_key_policy_json = aws.get_kms_key_policy(kms_key_id)

    # Get the principals for the KMS policy statement identified by the specified statement ID (sid).
    kms_key_sid_pattern = "Allow use of the key"
    kms_key_policy_principals = aws.get_kms_key_policy_principals(kms_key_policy_json, kms_key_sid_pattern)
    if args.verbose:
        PRINT(f"Principals for AWS KMS key: {kms_key_id}")
        for kms_key_principal in sorted(kms_key_policy_principals):
            PRINT(f"- {kms_key_principal}")

    # Find the Foursight roles which are missing from the KMS specific policy.
    foursight_roles_to_add = list(set(foursight_role_arns) - set(kms_key_policy_principals))
    if foursight_roles_to_add and len(foursight_roles_to_add) > 0:
        PRINT(f"Foursight roles not currently present in KMS key principals: {kms_key_id}")
        for foursight_role in foursight_roles_to_add:
            PRINT(f"- {foursight_role}")
    else:
        PRINT(f"All Foursight roles already currently present in KMS key principals: {kms_key_id}")
        exit_with_no_action("Nothing to do.")

    # Here there are one or more Foursight roles missing from the KMS policy. Confirm update.
    yes = yes_or_no(f"Update KMS policy with these roles for: {kms_key_id}?")
    if not yes:
        exit_with_no_action()

    # Here the user has confirmed update. Update the KMS key policy JSON (in place) and update in AWS.
    aws.amend_kms_key_policy(kms_key_policy_json, kms_key_sid_pattern, foursight_roles_to_add)
    aws.update_kms_key_policy(kms_key_id, kms_key_policy_json)


def main(override_argv: Optional[list] = None) -> None:
    """
    Main entry point for this script. Parses command-line arguments and calls the main logical entry point.

    :param override_argv: Raw command-line arguments for this invocation.
    """
    argp = argparse.ArgumentParser()
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
                      help=f"Your AWS session token.")
    argp.add_argument("--custom-dir", required=False, default=InfraDirectories.CUSTOM_DIR,
                      dest="custom_dir",
                      help=f"Alternate custom config directory to default: {InfraDirectories.CUSTOM_DIR}.")
    argp.add_argument("--no-confirm", required=False,
                      dest="confirm", action="store_false",
                      help="Behave as if all confirmation questions were answered yes.")
    argp.add_argument("--aws-region", required=False,
                      dest="aws_region",
                      help="The AWS region.")
    argp.add_argument("--s3-encrypt-key-id", required=False,
                      dest="s3_encrypt_key_id",
                      help="S3 encryption key ID.")
    argp.add_argument("--show", action="store_true", required=False)
    argp.add_argument("--verbose", action="store_true", required=False)
    args = argp.parse_args(override_argv)

    if (args.aws_access_key_id or args.aws_secret_access_key) and \
       not (args.aws_access_key_id and args.aws_secret_access_key):
        exit_with_no_action("Either none or both --aws-access-key-id and --aws-secret-access-key must be specified.")

    update_kms_policy(args)


if __name__ == "__main__":
    main()
