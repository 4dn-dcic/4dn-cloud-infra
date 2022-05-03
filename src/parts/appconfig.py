import json

from dcicutils.misc_utils import ignorable
from dcicutils.cloudformation_utils import dehyphenate
from troposphere import (
    AWS_ACCOUNT_ID,
    Ref,
    Template,
    Output,
)
try:
    from troposphere.elasticsearch import DomainEndpointOptions  # noQA
except ImportError:
    def DomainEndpointOptions(*args, **kwargs):  # noQA
        raise NotImplementedError('DomainEndpointOptions')
from troposphere.secretsmanager import Secret
from ..base import ConfigManager
from ..constants import Settings, Secrets, DeploymentParadigm
from ..exports import C4Exports
from ..part import C4Part
from ..parts.network import C4NetworkExports


ignorable(Output)


class C4AppConfigExports(C4Exports):
    """ Holds AppConfig export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = 'ExportElasticSearchURL'

    # Standalone, blue/green version is inlined
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
    STACK_NAME_TOKEN = 'appconfig'
    STACK_TITLE_TOKEN = 'AppConfig'
    SHARING = 'env'

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
        'ACCOUNT_NUMBER': AWS_ACCOUNT_ID,
        'S3_AWS_ACCESS_KEY_ID': None,
        'S3_AWS_SECRET_ACCESS_KEY': None,
        'ENCODED_AUTH0_CLIENT': ConfigManager.get_config_secret(Secrets.AUTH0_CLIENT, default=None),
        'ENCODED_AUTH0_SECRET': ConfigManager.get_config_secret(Secrets.AUTH0_SECRET, default=None),
        'ENV_NAME': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BS_ENV': CONFIGURATION_PLACEHOLDER,
        'ENCODED_DATA_SET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_ES_SERVER': CONFIGURATION_PLACEHOLDER,
        'ENCODED_IDENTITY': None,  # This is the name of the Secrets Manager with all our identity's secrets
        'ENCODED_FILE_UPLOAD_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_FILE_WFOUT_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BLOB_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_SYSTEM_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_METADATA_BUNDLES_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_TIBANNA_OUTPUT_BUCKET': CONFIGURATION_PLACEHOLDER,
        'LANG': CONFIGURATION_DEFAULT_LANG,
        'LC_ALL': CONFIGURATION_DEFAULT_LC_ALL,
        'RDS_HOSTNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_DB_NAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PORT': CONFIGURATION_DEFAULT_RDS_PORT,
        'RDS_USERNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PASSWORD': CONFIGURATION_PLACEHOLDER,
        'S3_ENCRYPT_KEY': ConfigManager.get_config_setting(Secrets.S3_ENCRYPT_KEY,
                                                           ConfigManager.get_s3_encrypt_key_from_file()),
        'ENCODED_SENTRY_DSN': CONFIGURATION_PLACEHOLDER,
        'reCaptchaKey': CONFIGURATION_PLACEHOLDER,
        'reCaptchaSecret': CONFIGURATION_PLACEHOLDER,
    }

    def build_template(self, template: Template) -> Template:
        """ Builds the appconfig template - builds GACs for blue/green if APP_DEPLOYMENT == blue/green """
        if ConfigManager.get_config_setting(Settings.APP_DEPLOYMENT) == DeploymentParadigm.BLUE_GREEN:
            gac_blue = self.application_configuration_secret(postfix='Blue')
            template.add_resource(gac_blue)
            template.add_output(self.output_configuration_secret(gac_blue, deployment_type='Blue'))
            gac_green = self.application_configuration_secret(postfix='Green')
            template.add_resource(gac_green)
            template.add_output(self.output_configuration_secret(gac_green, deployment_type='Green'))
        else:  # standalone
            application_configuration_secret = self.application_configuration_secret()
            template.add_resource(application_configuration_secret)
            template.add_output(self.output_configuration_secret(application_configuration_secret))
        return template

    def output_configuration_secret(self, application_configuration_secret, deployment_type='standalone'):
        """ Outputs GAC """
        logical_id = (self.name.logical_id(C4AppConfigExports.EXPORT_APPLICATION_CONFIG) +
                      deployment_type if deployment_type else '')
        export = (self.EXPORTS.export(C4AppConfigExports.EXPORT_APPLICATION_CONFIG +
                                      deployment_type if deployment_type else ''))
        return Output(
            logical_id,
            Description='Application Configuration Secret',
            Value=Ref(application_configuration_secret),
            Export=export
        )

    def application_configuration_secret(self, postfix=None) -> Secret:
        """ Returns the application configuration secret. Note that this pushes up just a
            template - you must fill it out according to the specification in the README.
        """
        logical_id = dehyphenate(self.name.logical_id(postfix if postfix else '')).replace('_', '')
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(self.APPLICATION_CONFIGURATION_TEMPLATE),
            Tags=self.tags.cost_tag_array()
        )
