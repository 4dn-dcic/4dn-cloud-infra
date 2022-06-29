import argparse
from .locations import InfraDirectories


def add_aws_credentials_args(args_parser: argparse.ArgumentParser) -> None:
    args_parser.add_argument("--aws-access-key-id", required=False,
                             dest="aws_access_key_id",
                             help=f"Your AWS access key ID; also requires --aws-access-secret-key.")
    args_parser.add_argument("--aws-credentials-dir", required=False,
                             dest="aws_credentials_dir",
                             help=f"Alternate full path to your custom AWS credentials directory.")
    args_parser.add_argument("--aws-credentials-name", required=False,
                             dest="aws_credentials_name",
                             help=f"The name of your AWS credentials,"
                                  f"e.g. <aws-credentials-name>"
                                  f" from {InfraDirectories.AWS_DIR}.<aws-credentials-name>.")
    args_parser.add_argument("--aws-region", required=False,
                             dest="aws_region",
                             help="The AWS region.")
    args_parser.add_argument("--aws-secret-access-key", required=False,
                             dest="aws_secret_access_key",
                             help=f"Your AWS access key ID; also requires --aws-access-key-id.")
    args_parser.add_argument("--aws-session-token", required=False,
                             dest="aws_session_token",
                             help=f"Your AWS session token.")
