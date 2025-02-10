import argparse
import boto3
import json
import sys
from typing import Optional


# EXAMPLE USAGE: python aws_get_secret.py C4AppConfigFoursightSmahtProduction/ENCODED_AUTH0_SECRET

def main():
    args_parser = argparse.ArgumentParser()
    args_parser.add_argument("secret_specifier", type=str)
    args = args_parser.parse_args()
    if (slash := args.secret_specifier.find("/")) > 0:
        secrets_name = args.secret_specifier[0:slash]
        secret_key = args.secret_specifier[slash + 1:]
        if secret_value := aws_get_secret_value(secrets_name, secret_key):
            print(secret_value)
            sys.exit(0)
    sys.exit(1)


def aws_get_secret_value(secrets_name: str, secret_key: str, raise_exception: bool = False) -> Optional[str]:
    try:
        if secrets_json := aws_get_secrets(secrets_name, raise_exception=raise_exception):
            return secrets_json[secret_key]
    except Exception as e:
        if raise_exception is True:
            raise e
    return None


def aws_get_secrets(secrets_name: str, raise_exception: bool = False) -> Optional[str]:
    try:
        secrets_manager = boto3.client("secretsmanager")
        secrets_response = secrets_manager.get_secret_value(SecretId=secrets_name)
        secrets_json = json.loads(secrets_response["SecretString"])
        return secrets_json
    except Exception as e:
        if raise_exception is True:
            raise e
    return None


if __name__ == "__main__":
    main()
