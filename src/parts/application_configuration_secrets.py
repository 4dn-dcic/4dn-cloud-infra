from ..base import ConfigManager
from ..constants import Settings, Secrets
from ..exports import C4DatastoreExportsMixin
from ..constants import C4DatastoreBase


class ApplicationConfigurationSecrets:

    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    # TODO/dmichaels/20220810: From C4DatastoreExports.
    @classmethod
    def get_es_url(cls):
        return ConfigManager.find_stack_output(C4DatastoreExportsMixin._ES_URL_EXPORT_PATTERN.match, value_only=True)

    # TODO/dmichaels/20220810: From C4Datastore.
    @classmethod
    def rds_db_username(cls):
        return ConfigManager.get_config_setting(Settings.RDS_DB_USERNAME,
                                                default=C4DatastoreBase.DEFAULT_RDS_DB_USERNAME)

    @classmethod
    def _add_placeholders(cls, template):
        return {
            k: cls.CONFIGURATION_PLACEHOLDER if v is None else v for k, v in template.items()
        }

    @classmethod
    def get(cls):
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        keys_values = {
            'deploying_iam_user': ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER),  # required
            'ACCOUNT_NUMBER': cls.CONFIGURATION_PLACEHOLDER,
            'S3_AWS_ACCESS_KEY_ID': None,
            'S3_AWS_SECRET_ACCESS_KEY': None,
            'ENCODED_AUTH0_CLIENT': ConfigManager.get_config_secret(Secrets.AUTH0_CLIENT, default=None),
            'ENCODED_AUTH0_SECRET': ConfigManager.get_config_secret(Secrets.AUTH0_SECRET, default=None),
            'ENV_NAME': env_name,
            'ENCODED_APPLICATION_BUCKET_PREFIX': ConfigManager.resolve_bucket_name("{application_prefix}"),
            'ENCODED_BS_ENV': env_name,
            'ENCODED_DATA_SET': 'deploy',
            'ENCODED_ES_SERVER': cls.get_es_url(),  # None,
            'ENCODED_FOURSIGHT_BUCKET_PREFIX': ConfigManager.resolve_bucket_name("{foursight_prefix}"),
            'ENCODED_IDENTITY': None,  # This is the name of the Secrets Manager with all our identity's secrets
            'ENCODED_FILE_UPLOAD_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_FILES_BUCKET),
            'ENCODED_FILE_WFOUT_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_WFOUT_BUCKET),
            'ENCODED_BLOB_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_BLOBS_BUCKET),
            'ENCODED_SYSTEM_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_SYSTEM_BUCKET),
            'ENCODED_METADATA_BUNDLES_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET),
            'ENCODED_S3_BUCKET_ORG': ConfigManager.get_config_setting(Settings.S3_BUCKET_ORG, default=None),
            'ENCODED_TIBANNA_OUTPUT_BUCKET':
                "",  # cls.application_layer_bucket(C4DatastoreExports.APPLICATION_TIBANNA_OUTPUT_BUCKET),
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
            'RDS_HOSTNAME': None,
            'RDS_DB_NAME': ConfigManager.get_config_setting(Settings.RDS_DB_NAME,
                                                            default=C4DatastoreBase.DEFAULT_RDS_DB_NAME),
            'RDS_NAME': ConfigManager.get_config_setting(Settings.RDS_NAME, default=None) or f"rds-{env_name}",
            'RDS_PORT': ConfigManager.get_config_setting(Settings.RDS_DB_PORT,
                                                         default=C4DatastoreBase.DEFAULT_RDS_DB_PORT),
            'RDS_USERNAME': ApplicationConfigurationSecrets.rds_db_username(),
            'RDS_PASSWORD': None,
            # foursight-envs bucket
            'GLOBAL_ENV_BUCKET': ConfigManager.resolve_bucket_name(ConfigManager.FSBucketTemplate.ENVS),
            'S3_ENCRYPT_KEY': ConfigManager.get_config_secret(Secrets.S3_ENCRYPT_KEY,
                                                              ConfigManager.get_s3_encrypt_key_from_file()),
            # 'S3_BUCKET_ENV': env_name,  # NOTE: not prod_bucket_env(env_name); see notes in resolve_bucket_name
            'ENCODED_S3_ENCRYPT_KEY_ID': ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None),
            'ENCODED_SENTRY_DSN': '',
            'ENCODED_URL': '',  # set this manually post orchestration
            'reCaptchaKey': ConfigManager.get_config_secret(Secrets.RECAPTCHA_KEY, default=None),
            'reCaptchaSecret': ConfigManager.get_config_secret(Secrets.RECAPTCHA_SECRET, default=None),
        }
        return cls._add_placeholders(keys_values)
