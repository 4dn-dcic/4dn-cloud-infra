import json

from dcicutils.misc_utils import ignorable
from troposphere import (
    # Join,
    Ref,
    Template,
    # Tags, Parameter,
    Output,
    # GetAtt, AccountId
)
try:
    from troposphere.elasticsearch import DomainEndpointOptions  # noQA
except ImportError:
    def DomainEndpointOptions(*args, **kwargs):  # noQA
        raise NotImplementedError('DomainEndpointOptions')
from troposphere.secretsmanager import Secret
from ..base import ConfigManager
from ..constants import Settings
from ..exports import C4Exports
from ..part import C4Part
from ..parts.network import C4NetworkExports


ignorable(Output)


class C4AppConfigExports(C4Exports):
    """ Holds AppConfig export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = 'ExportElasticSearchURL'

    EXPORT_APPLICATION_CONFIG = 'ExportApplicationConfig'

    # RDS Exports
    RDS_URL = 'ExportRDSURL'
    RDS_PORT = 'ExportRDSPort'

    # Output envs bucket and result bucket
    FOURSIGHT_ENV_BUCKET = 'ExportFoursightEnvsBucket'
    FOURSIGHT_RESULT_BUCKET = 'ExportFoursightResultBucket'
    FOURSIGHT_APPLICATION_VERSION_BUCKET = 'ExportFoursightApplicationVersionBucket'

    # Output production S3 bucket information
    APPLICATION_SYSTEM_BUCKET = 'ExportAppSystemBucket'
    APPLICATION_WFOUT_BUCKET = 'ExportAppWfoutBucket'
    APPLICATION_FILES_BUCKET = 'ExportAppFilesBucket'
    APPLICATION_BLOBS_BUCKET = 'ExportAppBlobsBucket'

    # Output SQS Queues
    APPLICATION_INDEXER_PRIMARY_QUEUE = 'ExportApplicationIndexerPrimaryQueue'
    APPLICATION_INDEXER_SECONDAY_QUEUE = 'ExportApplicationIndexerSecondaryQueue'
    APPLICATION_INDEXER_DLQ = 'ExportApplicationIndexerDLQ'
    APPLICATION_INGESTION_QUEUE = 'ExportApplicationIngestionQueue'
    APPLICATION_INDEXER_REALTIME_QUEUE = 'ExportApplicationIndexerRealtimeQueue'  # unused

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce amount
        # of manual configuration
        parameter = 'AppConfigStackNameParameter'
        super().__init__(parameter)


class C4AppConfig(C4Part):
    """ Defines the AppConfig stack - see resources created in build_template method. """
    STACK_NAME_TOKEN = "appconfig"
    STACK_TITLE_TOKEN = "AppConfig"
    SHARING = 'env'

    APPLICATION_SECRET_STRING = 'ApplicationConfiguration'
    RDS_SECRET_STRING = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4AppConfigExports()
    NETWORK_EXPORTS = C4NetworkExports()
    # TODO only use configuration placeholder for orchestration time values; otherwise, use src.constants values
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    CONFIGURATION_DEFAULT_LANG = 'en_US.UTF-8'
    CONFIGURATION_DEFAULT_LC_ALL = 'en_US.UTF-8'
    CONFIGURATION_DEFAULT_RDS_PORT = '5432'

    APPLICATION_CONFIGURATION_TEMPLATE = {
        'deploying_iam_user': CONFIGURATION_PLACEHOLDER,
        'Auth0Client': CONFIGURATION_PLACEHOLDER,
        'Auth0Secret': CONFIGURATION_PLACEHOLDER,
        'ENV_NAME': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BS_ENV': CONFIGURATION_PLACEHOLDER,
        'ENCODED_DATA_SET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_ES_SERVER': CONFIGURATION_PLACEHOLDER,
        'ENCODED_FILES_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_WFOUT_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BLOBS_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_SYSTEM_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_METADATA_BUNDLE_BUCKET': CONFIGURATION_PLACEHOLDER,
        'LANG': CONFIGURATION_DEFAULT_LANG,
        'LC_ALL': CONFIGURATION_DEFAULT_LC_ALL,
        # 'RDS_HOSTNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_DB_NAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PORT': CONFIGURATION_DEFAULT_RDS_PORT,
        'RDS_USERNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PASSWORD': CONFIGURATION_PLACEHOLDER,
        'S3_ENCRYPT_KEY': CONFIGURATION_PLACEHOLDER,
        'SENTRY_DSN': CONFIGURATION_PLACEHOLDER,
        'reCaptchaKey': CONFIGURATION_PLACEHOLDER,
        'reCaptchaSecret': CONFIGURATION_PLACEHOLDER,
    }

    def build_template(self, template: Template) -> Template:
        application_configuration_secret = self.application_configuration_secret()
        template.add_resource(application_configuration_secret)
        template.add_output(self.output_configuration_secret(application_configuration_secret))
        return template

    def output_configuration_secret(self, application_configuration_secret):
        logical_id = self.name.logical_id(C4AppConfigExports.EXPORT_APPLICATION_CONFIG)
        return Output(
            logical_id,
            Description='Application Configuration Secret',
            Value=Ref(application_configuration_secret),
            Export=self.EXPORTS.export(C4AppConfigExports.EXPORT_APPLICATION_CONFIG)
        )

    def application_configuration_secret(self) -> Secret:
        """ Returns the application configuration secret. Note that this pushes up just a
            template - you must fill it out according to the specification in the README.
        """
        env_identifier = ConfigManager.get_config_setting(Settings.ENV_NAME).replace('-', '')
        if not env_identifier:
            raise Exception('Did not set required key in .env! Should never get here.')
        logical_id = self.name.logical_id(self.APPLICATION_SECRET_STRING) + env_identifier
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(self.APPLICATION_CONFIGURATION_TEMPLATE),
            Tags=self.tags.cost_tag_array()
        )
