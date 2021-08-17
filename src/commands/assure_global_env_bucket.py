import argparse
import boto3
import json

from dcicutils.command_utils import yes_or_no
from ..base import ConfigManager
from ..constants import Settings
from ..parts.datastore import C4DatastoreExports
from ..parts.ecs import C4ECSApplicationExports


def configure_env_bucket(env=None):
    """
    This will upload an appropriate entry into the global env bucket for the given env,
    which defaults to the config-declared environment if not specified.
    """
    global_env_bucket = C4DatastoreExports.get_env_bucket()  # ConfigManager.get_config_setting(Settings.GLOBAL_ENV_BUCKET)
    s3 = boto3.client('s3')
    env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
    content = {
        "fourfront": C4ECSApplicationExports.get_application_url(env) + ":80",
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
    if yes_or_no(f"Upload this into {env} in account {ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)}?"):
        s3.put_object(Bucket=global_env_bucket, Key=env, Body=body)
    else:
        print("Aborted.")


def main():
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=None, type=str)
    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():
        configure_env_bucket(env=args.env_name)


if __name__ == '__main__':
    main()
