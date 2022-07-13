import argparse
from .paths import InfraDirectories
from .misc_utils import exit_with_no_action


def add_aws_credentials_args(args_parser: argparse.ArgumentParser) -> None:
    """
    Adds some standard AWS related arguments to the given argparse.ArgumentParser.

    :param args_parser: The argparse.ArgumentParser to add arguments to.
    """
    args_parser.add_argument("--aws-access-key-id", required=False,
                             help=f"Your AWS access key ID; also requires --aws-access-secret-key.")
    args_parser.add_argument("--aws-credentials-dir", required=False,
                             help=f"Alternate full path to your custom AWS credentials directory.")
    args_parser.add_argument("--aws-credentials-name", required=False,
                             help=f"The name of your AWS credentials,"
                                  f"e.g. <aws-credentials-name>"
                                  f" from {InfraDirectories.AWS_DIR}.<aws-credentials-name>.")
    args_parser.add_argument("--aws-region", required=False,
                             help="The AWS region.")
    args_parser.add_argument("--aws-secret-access-key", required=False,
                             help=f"Your AWS access key ID; also requires --aws-access-key-id.")
    args_parser.add_argument("--aws-session-token", required=False,
                             help=f"Your AWS session token.")


def validate_aws_credentials_args(args) -> None:
    if ((args.aws_access_key_id or args.aws_secret_access_key)
       and not (args.aws_access_key_id and args.aws_secret_access_key)):
        exit_with_no_action("Either none or both --aws-access-key-id and --aws-secret-access-key must be specified.")
    if args.aws_access_key_id and args.aws_credentials_dir:
        exit_with_no_action("Cannot specify both --aws-credentials-dir and --aws-access-key-id.")
