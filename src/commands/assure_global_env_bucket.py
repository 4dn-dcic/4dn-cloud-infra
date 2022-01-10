import argparse
import boto3
import json
import re

from dcicutils.command_utils import yes_or_no
from dcicutils.env_utils import EnvNames, PublicUrlParts, ClassificationParts
from dcicutils.misc_utils import PRINT, ignored, string_list, find_association
from urllib.parse import urlparse
from ..base import (
    ConfigManager,
    ENV_NAME, S3_BUCKET_ORG, S3_IS_ENCRYPTED, APP_KIND,
)
from ..constants import Settings
from ..parts.datastore import C4DatastoreExports
from ..parts.ecs import C4ECSApplicationExports
from ..commands.find_resources import get_portal_url, get_foursight_url


e = EnvNames
p = PublicUrlParts
c = ClassificationParts


def parse_env_to_host_mapping(mapping):
    parts = [part.strip() for part in mapping.split("=")]
    n_parts = len(parts)
    if n_parts == 2:
        return parts[0], parts[0], parts[1]
    elif n_parts == 3:
        return parts[0], parts[1], parts[2]
    else:
        raise ValueError(f"Expected syntax 'env=host' or 'public_env=env=host' in: {mapping!r}.")


HOST_REGEXP = re.compile('^(?:(https?)://)?(.*[^/])/?$')


def parse_public_url_mapping(mapping, full_env_prefix, http_scheme):
    public_env_name, internal_env_name, host = parse_env_to_host_mapping(mapping)
    m = HOST_REGEXP.match(host)
    if not m:  # Hard to imagine what won't match other than a null string
        raise ValueError("Bad host format: {host!r}")
    parsed_http_scheme, host_name = m.groups()
    if parsed_http_scheme:
        http_scheme = parsed_http_scheme
    http_scheme = http_scheme or 'https'
    full_internal_env_name = internal_env_name
    if full_env_prefix and not internal_env_name.startswith(full_env_prefix):
        full_internal_env_name = full_env_prefix + internal_env_name
    return {
        p.NAME: public_env_name,
        p.URL: f"{http_scheme}://{host_name}",
        p.HOST: host_name,
        p.ENVIRONMENT: full_internal_env_name,
    }


def parse_public_url_mappings(mappings, full_env_prefix, http_scheme=None):
    res = [
        parse_public_url_mapping(mapping, full_env_prefix=full_env_prefix, http_scheme=http_scheme)
        for mapping in string_list(mappings)
    ]
    return res


VIEW_REGEXP = re.compile("(http.*/api/view/)[^/]+")


def make_env_utils_config(env_name=None, org=None,
                          mirror_env_name=None, default_data_set=None, indexer_env_name=None,
                          dev_env_domain_suffix=None, stg_mirroring_enabled=None,
                          full_env_prefix=None, test_envs=None, public_url_mappings=None, hotseat_envs=None) -> dict:

    env_name = env_name or ENV_NAME
    org = org or S3_BUCKET_ORG

    def defaulted_setting(setting, setting_name, default=None):
        return setting or ConfigManager.get_config_setting(setting_name, default=default)

    default_data_set = defaulted_setting(default_data_set, Settings.ENV_UTILS_DEFAULT_DATA_SET, default='prod')
    dev_env_domain_suffix = defaulted_setting(dev_env_domain_suffix, Settings.ENV_UTILS_DEV_ENV_DOMAIN_SUFFIX,
                                              default=".elb.amazonaws.com")
    full_env_prefix = defaulted_setting(full_env_prefix,Settings.ENV_UTILS_FULL_ENV_PREFIX, default="")
    hotseat_envs = defaulted_setting(hotseat_envs, Settings.ENV_UTILS_HOTSEAT_ENVS)
    indexer_env_name = defaulted_setting(indexer_env_name, Settings.ENV_UTILS_INDEXER_ENV_NAME,
                                         default=f"{env_name}-indexer")
    mirror_env_name = defaulted_setting(mirror_env_name, Settings.ENV_UTILS_MIRROR_ENV_NAME)
    public_url_mappings = defaulted_setting(public_url_mappings, Settings.ENV_UTILS_PUBLIC_URL_MAPPINGS, default={})
    test_envs = defaulted_setting(test_envs, Settings.ENV_UTILS_TEST_ENVS)

    if isinstance(hotseat_envs, str):
        hotseat_envs = string_list(hotseat_envs)
    if isinstance(test_envs, str):
        test_envs = string_list(test_envs)
    if isinstance(public_url_mappings, str):
        public_url_mappings = parse_public_url_mappings(public_url_mappings, full_env_prefix=full_env_prefix)

    public_url_mappings = public_url_mappings or {}

    try:
        portal_url = get_portal_url(env_name=env_name)
        parsed = urlparse(portal_url)
        portal_host = parsed.hostname
        pos = portal_host.index('.')
        dev_env_domain_suffix = portal_host[pos:]
    except Exception as error_obj:
        ignored(error_obj)
        pass  # already did default setup earlier

    foursight_url_prefix = "http://foursight/api/view/"
    try:
        foursight_url = get_foursight_url(env_name=env_name)
        parsed = VIEW_REGEXP.match(foursight_url)
        if parsed:
            foursight_url_prefix = parsed.group(1)
    except Exception as error_obj:
        ignored(error_obj)
        pass  # already did default setup earlier

    env_utils_config = {
        e.DEV_DATA_SET_TABLE: {env_name: default_data_set},
        e.DEV_ENV_DOMAIN_SUFFIX: dev_env_domain_suffix,
        e.FOURSIGHT_URL_PREFIX: foursight_url_prefix,
        e.FULL_ENV_PREFIX: full_env_prefix,
        e.HOTSEAT_ENVS: hotseat_envs or [],
        e.INDEXER_ENV_NAME: indexer_env_name,
        e.IS_LEGACY: False,
        e.ORCHESTRATED_APP: 'cgap',
        e.PRD_ENV_NAME: env_name,
        e.PUBLIC_URL_TABLE: public_url_mappings,
        e.STAGE_MIRRORING_ENABLED: stg_mirroring_enabled or False,
        e.STG_ENV_NAME: mirror_env_name,
        e.TEST_ENVS: test_envs or [],
        e.WEBPROD_PSEUDO_ENV: env_name,
    }

    return env_utils_config


def configure_env_bucket(env_name=None,
                         mirror_env_name=None, default_data_set=None, indexer_env_name=None, org=None,
                         dev_env_domain_suffix=None, stg_mirroring_enabled=None,
                         full_env_prefix=None, test_envs=None, public_url_mappings=None, hotseat_envs=None):
    """
    This will upload an appropriate entry into the global env bucket for the given env,
    which defaults to the config-declared environment if not specified.
    """
    global_env_bucket = C4DatastoreExports.get_env_bucket()
    s3 = boto3.client('s3')
    env_name = env_name or ConfigManager.get_config_setting(Settings.ENV_NAME)

    env_utils_config = make_env_utils_config(env_name=env_name,
                                             mirror_env_name=mirror_env_name, default_data_set=default_data_set,
                                             indexer_env_name=indexer_env_name, org=org,
                                             dev_env_domain_suffix=dev_env_domain_suffix,
                                             stg_mirroring_enabled=stg_mirroring_enabled,
                                             full_env_prefix=full_env_prefix, test_envs=test_envs,
                                             public_url_mappings=public_url_mappings, hotseat_envs=hotseat_envs)

    internal_server_url = C4ECSApplicationExports.get_application_url(env_name) + ":80"
    entry = find_association(env_utils_config.get(e.PUBLIC_URL_TABLE, []), **{p.ENVIRONMENT: env_name})
    public_server_url = entry.get(p.URL) if entry else None

    content = {
        "fourfront": public_server_url or internal_server_url,
        "es": "https://" + C4DatastoreExports.get_es_url() + ":443",
        "ff_env": env_name,
    }

    content.update(env_utils_config)

    try:
        # print(f"Bucket={global_env_bucket}, Key={env}")
        s3.head_bucket(Bucket=global_env_bucket)  # check if bucket exists
    except Exception as error_obj:
        if 'NoSuchBucket' in str(error_obj):
            PRINT("First create buckets! %s" % str(error_obj))
        raise
    body = json.dumps(content, indent=2).encode('utf-8')
    PRINT(f"To be uploaded: {body.decode('utf-8')}")
    if yes_or_no(f"Upload this into {env_name} in account {ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)}?"
                 f" with encryption={S3_IS_ENCRYPTED}"):
        if S3_IS_ENCRYPTED:
            s3.put_object(Bucket=global_env_bucket, Key=env_name, Body=body,
                          ServerSideEncryption='aws:kms',
                          SSEKMSKeyId=ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID), )
        else:
            s3.put_object(Bucket=global_env_bucket, Key=env_name, Body=body)
    else:
        PRINT("Aborted.")

def explain_boolean_default(name, value, default):
    if value == default:
        return f"The default is {name}={default}, so this is a no-op."
    else:
        return f"The default is {name}={default}."

def main():
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--default-data-set', '--default_data_set', default=None, type=str,
                        help="The name of the default data set (usually 'test' or 'prod').")
    parser.add_argument('--dev-env-domain-suffix', '--dev_env_domain_suffix', default=None, type=str,
                        help="For classification only, a piece of text expected to appear"
                             " on the end of all dev env domain names.")
    parser.add_argument('--env-name', '--env_name', default=None, type=str,
                        help='The environment name to assure')
    parser.add_argument('--full-env-prefix', '--full_env_prefix', default=None, type=str,
                        help="The prefix that should appear on all full envrionment names."
                             " If not specified, the org name plus a hyphen (e.g., 'acme-') is the default.")
    parser.add_argument('--hotseat-envs', '--hotseat_envs', default=None, type=str,
                        help="A comma-separated list of hotseat environments.")
    parser.add_argument('--indexer-env-name', '--indexer_env_name', default=None, type=str,
                        help="The name of an environment to use, if the default isn't OK.")
    parser.add_argument('--mirror-env-name', '--mirror_env_name', default=None, type=str,
                        help="The name of a mirror environment to use, if any.")
    parser.add_argument('--org', default=None, type=str,
                        help="The organization name.")
    parser.add_argument('--public-url-mappings', '--public_url_mappings', default=None, type=str,
                        help="A comma-separated list of public URL mapping specs."
                             " Each spec should be name=host or public_name=internal_name=host.")
    parser.add_argument('--stg-mirroring-enabled', '--stg_mirroring_enabled', default=None,
                        action="store_true", dest='stg_mirroring_enabled',
                        help="If supplied, enables stage mirroring. (Specifying a mirror name is not enough.)")
    parser.add_argument('--test-envs', '--test_envs', default=None, type=str,
                        help="A comma-separated list of test environments.")

    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():

        configure_env_bucket(
            env_name=(args.env_name or ENV_NAME),
            org=(args.org or S3_BUCKET_ORG),
            # The rest are defaulted elsewhere.
            default_data_set=args.default_data_set,
            dev_env_domain_suffix=args.dev_env_domain_suffix,
            full_env_prefix=args.full_env_prefix,
            hotseat_envs=args.hotseat_envs,
            indexer_env_name=args.indexer_env_name,
            mirror_env_name=args.mirror_env_name,
            stg_mirroring_enabled=args.stg_mirroring_enabled,
            public_url_mappings=args.public_url_mappings,
            test_envs=args.test_envs,
        )


if __name__ == '__main__':
    main()
