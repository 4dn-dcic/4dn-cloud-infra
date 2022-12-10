import argparse
import boto3
import json
import re

from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from dcicutils.ecs_utils import COMMON_REGION
from ..base import ConfigManager
from ..constants import Settings
from ..parts.datastore import C4DatastoreExports
from .find_resources import get_foursight_url
from ..parts.ecs import C4ECSApplicationExports


def strip_scheme(url: str):  # TODO move to utils? or use urlparse?
    return re.sub(r'^https?:\/\/', '', url)


def configure_env_utils_ecosystem(env=None, url_override=None):
    """ Builds an env_utils compatible main.ecosystem entry in GLOBAL_ENV_BUCKET. """
    global_env_bucket = C4DatastoreExports.get_env_bucket()
    s3 = boto3.client('s3')
    env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
    full_url = url_override if url_override else C4ECSApplicationExports.get_application_url(env_name=env)
    content = {
        "default_workflow_env": env,
        "dev_data_set_table": {
            env: "deploy"  # is this used?
        },
        "dev_env_domain_suffix": f".{COMMON_REGION}.elb.amazonaws.com",  # TODO: region should maybe be configurable
        "foursight_bucket_table": {
            env: {
                "dev": C4DatastoreExports.get_foursight_result_bucket(),
                "prod": C4DatastoreExports.get_foursight_result_bucket()
            }
        },
        "foursight_url_prefix": '',  # TODO: this value must be filled in
        "full_env_prefix": "cgap-",
        "hotseat_envs": [],
        "is_legacy": False,
        "orchestrated_app": "cgap",
        "prd_env_name": env,
        "public_url_table": [
            {
                "name": env,
                "url": full_url,
                "host": strip_scheme(full_url),
                "environment": env
            }
        ],
        "stage_mirroring_enabled": False,
        "stg_env_name": None,
        "test_envs": [],
        "webprod_pseudo_env": env
    }

    body = json.dumps(content, indent=2).encode('utf-8')
    _upload_to_s3(s3=s3, bucket=global_env_bucket, key='main.ecosystem', env=env, body=body)


def configure_env_utils_bucket_entry(env=None):
    """ Builds an env_utils compatible GLOBAL_ENV_BUCKET entry. """
    global_env_bucket = C4DatastoreExports.get_env_bucket()
    s3 = boto3.client('s3')
    env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
    content = {
        'ecosystem': 'main'
    }
    body = json.dumps(content, indent=2).encode('utf-8')
    _upload_to_s3(s3=s3, bucket=global_env_bucket, key=env, env=env, body=body)


def configure_env_utils(env=None, url_override=None):
    """ Bootstraps GLOBAL_ENV_BUCKET with an env_utils compatible configuration for a standalone environment.
    """
    configure_env_utils_ecosystem(env=None, url_override=url_override)
    configure_env_utils_bucket_entry(env=env)


def _upload_to_s3(*, s3, bucket, key, env, body):
    PRINT(f"To be uploaded: {body.decode('utf-8')} into s3://{bucket}/{key}")
    s3_encrypt_key_id = ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None)
    if yes_or_no(f"Upload this into {env} in account {ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)}?"
                 f" with s3_encrypt_key_id={s3_encrypt_key_id}"):
        if s3_encrypt_key_id:
            s3.put_object(Bucket=bucket, Key=key, Body=body,
                          ServerSideEncryption='aws:kms',
                          SSEKMSKeyId=s3_encrypt_key_id)
        else:
            s3.put_object(Bucket=bucket, Key=env, Body=body)
    else:
        PRINT("Aborted.")


def main():
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=None, type=str)
    parser.add_argument('--url', help='The URL to use for this env (if not the autogenerated one)', default=None,
                        type=str)
    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():
        configure_env_utils(env=args.env_name, url_override=args.url)


if __name__ == '__main__':
    main()
