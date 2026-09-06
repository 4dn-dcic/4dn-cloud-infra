import mock

from src.base import ConfigManager
from src.constants import Settings
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.datastore import C4Datastore, C4DatastoreExports


# Regression coverage for the SRCE Foursight NoSuchBucket bug: the GAC (Global Application
# Configuration) secret template used to leave ENCODED_SYSTEM_BUCKET (and four sibling
# application-layer bucket names) as an empty-string placeholder. Because an empty string is
# falsy, dcicutils.deployment_utils's ini-generation fell back to its own default bucket-name
# formula, which appends the env name a second time onto ENCODED_APPLICATION_BUCKET_PREFIX --
# a value that (per this repo's convention) already contains the env name -- producing a bucket
# name that 4dn-cloud-infra never actually provisions. These tests assert that each of the five
# GAC bucket secret values is instead computed via the same canonical machinery
# (ConfigManager.resolve_bucket_name) that C4Datastore uses to name the buckets it actually
# creates, so the two can never drift apart again.

# (secret key, datastore export name, bucket-name template, expected bucket-name suffix)
BUCKET_EXPORT_TEMPLATE_PAIRS = [
    ("ENCODED_SYSTEM_BUCKET",
     C4DatastoreExports.APPLICATION_SYSTEM_BUCKET, ConfigManager.AppBucketTemplate.SYSTEM, "system"),
    ("ENCODED_FILE_UPLOAD_BUCKET",
     C4DatastoreExports.APPLICATION_FILES_BUCKET, ConfigManager.AppBucketTemplate.FILES, "files"),
    ("ENCODED_FILE_WFOUT_BUCKET",
     C4DatastoreExports.APPLICATION_WFOUT_BUCKET, ConfigManager.AppBucketTemplate.WFOUT, "wfoutput"),
    ("ENCODED_BLOB_BUCKET",
     C4DatastoreExports.APPLICATION_BLOBS_BUCKET, ConfigManager.AppBucketTemplate.BLOBS, "blobs"),
    ("ENCODED_METADATA_BUNDLES_BUCKET",
     C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET,
     ConfigManager.AppBucketTemplate.METADATA_BUNDLES, "metadata-bundles"),
]


def _config_setting_stub(env_name):
    """
    Stands in for ConfigManager.get_config_setting, returning only a controlled ENCODED_ENV_NAME
    (env.name) and otherwise falling back to whatever default the caller supplied -- avoiding any
    dependency on a real custom/config.json or live AWS credentials.
    """
    def _get(var, default=None, use_default_if_empty=True):
        if var == Settings.ENV_NAME:
            return env_name
        return default
    return _get


def test_gac_bucket_secrets_match_canonical_provisioned_bucket_names():
    """
    For a realistic env name (mirroring the actual smaht-dev-srce failure), each of the five
    GAC bucket secret values must: (a) equal what C4Datastore.application_layer_bucket actually
    provisions for the corresponding export, and (b) contain the env name exactly once.
    """
    env_name = "smaht-dev-srce"
    with mock.patch.object(ConfigManager, "get_config_setting", side_effect=_config_setting_stub(env_name)):
        for secret_key, export_name, template, suffix in BUCKET_EXPORT_TEMPLATE_PAIRS:
            generated = ConfigManager.resolve_bucket_name(template)
            canonical = C4Datastore.application_layer_bucket(export_name)
            assert generated == canonical, (
                f"{secret_key}: generated {generated!r} does not match the actually-provisioned "
                f"bucket name {canonical!r}"
            )
            assert generated == f"{env_name}-application-{suffix}"
            assert generated.count(env_name) == 1, (
                f"{secret_key}: env name {env_name!r} appears {generated.count(env_name)} times "
                f"in {generated!r} (expected exactly once -- this is the doubled-name bug)"
            )


def test_gac_bucket_secrets_match_canonical_bucket_even_when_env_name_overlaps_a_suffix():
    """
    Disconfirming case: env_name here contains the bucket suffix itself ("system"), so a naive
    "env name appears exactly once in the bucket name" substring check is not sufficient by
    itself -- it would also pass for a name that happened to reuse "system" from within the
    env name rather than from the suffix. The real guarantee is exact equality with the
    canonical, already-provisioned bucket name, which is what this test asserts.
    """
    env_name = "acme-system-dev"
    with mock.patch.object(ConfigManager, "get_config_setting", side_effect=_config_setting_stub(env_name)):
        generated = ConfigManager.resolve_bucket_name(ConfigManager.AppBucketTemplate.SYSTEM)
        canonical = C4Datastore.application_layer_bucket(C4DatastoreExports.APPLICATION_SYSTEM_BUCKET)
        assert generated == canonical == f"{env_name}-application-system"


def test_build_initial_values_populates_bucket_secrets_from_canonical_machinery():
    """
    End-to-end (within this repo) check of the actual code path that used to ship blank
    placeholders: ApplicationConfigurationSecrets.build_initial_values() must populate all five
    bucket secrets with real, non-empty, correctly-suffixed values -- not "" -- for every
    generated GAC secret.
    """
    env_name = "smaht-dev-srce"
    with mock.patch.object(ConfigManager, "get_config_setting", side_effect=_config_setting_stub(env_name)), \
         mock.patch.object(ApplicationConfigurationSecrets, "get_es_url", return_value="some-es-url:443"), \
         mock.patch.object(ApplicationConfigurationSecrets, "rds_db_username", return_value="test-rds-user"), \
         mock.patch.object(ConfigManager, "get_s3_encrypt_key_from_file", return_value=None):
        values = ApplicationConfigurationSecrets.build_initial_values()

    for secret_key, export_name, template, suffix in BUCKET_EXPORT_TEMPLATE_PAIRS:
        expected = f"{env_name}-application-{suffix}"
        assert values[secret_key] == expected, (
            f"{secret_key} was {values[secret_key]!r}, expected {expected!r} (must not be blank)"
        )
        assert values[secret_key] != "", f"{secret_key} regressed to the empty-string placeholder"

    # Tibanna output is intentionally untouched by this fix (different, non-doubling template;
    # confirmed correct in the live SRCE environment) -- still left for manual/other population.
    assert values["ENCODED_TIBANNA_OUTPUT_BUCKET"] == ""
