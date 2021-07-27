import argparse
import boto3
import json
import datetime
import os
import re

from dcicutils.command_utils import yes_or_no
from src.parts.datastore import C4DatastoreExports
from src.parts.ecs import C4ECSApplicationExports
from src.constants import ENV_NAME, GLOBAL_ENV_BUCKET, ACCOUNT_NUMBER
from src.base import ConfigManager


def configure_env_bucket(env=None):
    # We don't do 'global_env_bucket = C4DatastoreExports.get_envs_bucket()' because the GLOBAL_ENV_BUCKET
    # is in the config and was presumably made to the same spec.
    global_env_bucket = ConfigManager.get_config_setting(GLOBAL_ENV_BUCKET)
    s3 = boto3.client('s3')
    env = env or ConfigManager.get_config_setting(ENV_NAME)
    content = {
        "fourfront": C4ECSApplicationExports.get_application_url(env),
        "es": "https://" + C4DatastoreExports.get_es_url() + ":443",
        "ff_env": env,
    }
    try:
        # print(f"Bucket={global_env_bucket}, Key={env}")
        s3.head_bucket(Bucket=global_env_bucket)  # check if bucket exists
    except Exception as e:
        if 'NoSuchBucket' in str(e):
            print("first create buckets! %s" % str(e))
        raise
    body = json.dumps(content, indent=2).encode('utf-8')
    print(f"To be uploaded: {body.decode('utf-8')}")
    if yes_or_no(f"Uplaod this into {env} in account {ConfigManager.get_config_setting(ACCOUNT_NUMBER)}?"):
        s3.put_object(Bucket=global_env_bucket, Key=env, Body=body)
    else:
        print("Aborted.")


def main():
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=None, type=str)
    parser.add_argument('--creds_dir', default=ConfigManager.compute_aws_default_test_creds_dir(),
                        help='Sets aws creds dir', type=str)
    args = parser.parse_args()
    # print(f"creds_dir={args.creds_dir}")
    ConfigManager.set_creds_dir(args.creds_dir)  # This must be done as early as possible for good consistency.

    with ConfigManager.validate_and_source_configuration(creds_dir=ConfigManager.compute_aws_default_test_creds_dir()):
        configure_env_bucket(env=args.env_name)


if __name__ == '__main__':
    main()
