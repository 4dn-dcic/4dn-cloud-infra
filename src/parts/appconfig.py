import json
import re
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
from .application_configuration_secrets import ApplicationConfigurationSecrets
from ..base import ConfigManager, APP_DEPLOYMENT
from ..constants import Secrets, DeploymentParadigm
from ..exports import C4Exports
from ..part import C4Part
from ..parts.network import C4NetworkExports
from ..constants import C4AppConfigBase


ignorable(Output)


class C4AppConfigExports(C4Exports):
    """ Holds AppConfig export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = 'ExportElasticSearchURL'

    # Standalone, blue/green version is inlined
    EXPORT_APPLICATION_CONFIG = 'ExportApplicationConfig'
    EXPORT_FOURSIGHT_APPLICATION_CONFIG = 'ExportFoursightApplicationConfig'
    # Build-time / runtime secrets — values stubbed by the appconfig stack, filled in post-deploy.
    # Each Output exports the secret's ARN so downstream stacks (e.g. codebuild) can grant
    # GetSecretValue and reference SECRETS_MANAGER-typed env vars without hardcoding ARNs.
    # (DockerHub credentials live in the ecosystem-scoped shared_secrets stack instead — see
    #  C4SharedSecretsExports — so multiple env-scoped appconfig stacks share one secret.)
    EXPORT_FALCON_CID = 'ExportFalconCID'
    EXPORT_FALCON_CLIENT_ID = 'ExportFalconClientID'
    EXPORT_FALCON_CLIENT_SECRET = 'ExportFalconClientSecret'
    _ENV_BUCKET_EXPORT_PATTERN = re.compile(".*AppConfig.*Env.*Bucket")

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

    @classmethod
    def get_env_bucket(cls):
        return ConfigManager.find_stack_output(cls._ENV_BUCKET_EXPORT_PATTERN.match, value_only=True)


class C4AppConfig(C4AppConfigBase, C4Part):
    """ Defines the AppConfig stack - see resources created in build_template method. """
    SHARING = 'env'

    RDS_SECRET_STRING = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4AppConfigExports()
    NETWORK_EXPORTS = C4NetworkExports()

    # Falcon credentials are env-scoped — each appconfig deployment gets its own set.
    FALCON_CID_LOGICAL_SUFFIX = 'FalconCID'
    FALCON_CLIENT_ID_LOGICAL_SUFFIX = 'FalconClientID'
    FALCON_CLIENT_SECRET_LOGICAL_SUFFIX = 'FalconClientSecret'
    # TODO only use configuration placeholder for orchestration time values; otherwise, use src.constants values
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    CONFIGURATION_DEFAULT_LANG = 'en_US.UTF-8'
    CONFIGURATION_DEFAULT_LC_ALL = 'en_US.UTF-8'
    CONFIGURATION_DEFAULT_RDS_PORT = '5432'

    # dmichaels/2022-08-10: Moved into ApplicationConfigurationSecrets.build_initial_values().
    OBSOLETE_APPLICATION_CONFIGURATION_TEMPLATE = {
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
        """ Builds the appconfig template - builds GACs for blue/green if APP_DEPLOYMENT == blue/green.
            Always builds a single Foursight configuration secret with identical key/value structure
            (foursight is not blue/green'd; only ECS is). """
        if APP_DEPLOYMENT == DeploymentParadigm.BLUE_GREEN:
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

        # Single foursight secret regardless of deployment paradigm.
        foursight_configuration_secret = self.foursight_configuration_secret()
        template.add_resource(foursight_configuration_secret)
        template.add_output(self.output_foursight_configuration_secret(foursight_configuration_secret))

        # Build-time / runtime credentials — stubbed here, populated post-deploy via
        # `aws secretsmanager put-secret-value ...`.  ARNs exported so downstream stacks
        # (e.g. codebuild) can attach IAM policies and reference SECRETS_MANAGER env vars.
        # (DockerHub credentials are owned by the ecosystem-scoped shared_secrets stack;
        #  see C4SharedSecrets in src/parts/shared_secrets.py.)
        falcon_cid = self.falcon_cid_secret()
        template.add_resource(falcon_cid)
        template.add_output(self.output_simple_secret_arn(
            falcon_cid, C4AppConfigExports.EXPORT_FALCON_CID,
            'Crowdstrike Falcon Customer ID (CID)'))

        falcon_client_id = self.falcon_client_id_secret()
        template.add_resource(falcon_client_id)
        template.add_output(self.output_simple_secret_arn(
            falcon_client_id, C4AppConfigExports.EXPORT_FALCON_CLIENT_ID,
            'Crowdstrike Falcon API Client ID'))

        falcon_client_secret = self.falcon_client_secret_secret()
        template.add_resource(falcon_client_secret)
        template.add_output(self.output_simple_secret_arn(
            falcon_client_secret, C4AppConfigExports.EXPORT_FALCON_CLIENT_SECRET,
            'Crowdstrike Falcon API Client Secret'))

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
            SecretString=json.dumps(ApplicationConfigurationSecrets.build_initial_values(), indent=2),
            Tags=self.tags.cost_tag_array()
        )

    def foursight_configuration_secret(self, postfix=None) -> Secret:
        """ Returns a Foursight configuration secret with the same key/value structure as the
            application configuration secret. Foursight reads/owns this independently from the
            portal so it can be filled in without touching the portal's GAC.
        """
        suffix = 'Foursight' + (postfix or '')
        logical_id = dehyphenate(self.name.logical_id(suffix)).replace('_', '')
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This secret defines the foursight configuration for the orchestrated environment.',
            SecretString=json.dumps(ApplicationConfigurationSecrets.build_initial_values(), indent=2),
            Tags=self.tags.cost_tag_array()
        )

    def output_foursight_configuration_secret(self, foursight_configuration_secret, deployment_type='standalone'):
        """ Outputs the foursight configuration secret reference (mirrors output_configuration_secret). """
        base = C4AppConfigExports.EXPORT_FOURSIGHT_APPLICATION_CONFIG + (deployment_type if deployment_type else '')
        logical_id = self.name.logical_id(base)
        export = self.EXPORTS.export(base)
        return Output(
            logical_id,
            Description='Foursight Application Configuration Secret',
            Value=Ref(foursight_configuration_secret),
            Export=export
        )

    def _falcon_stub_secret(self, suffix: str, description: str) -> Secret:
        """ Single-string Falcon secret stub (no JSON wrapper). Plain string makes the
            CodeBuild SECRETS_MANAGER env-var reference one-liner — no `:key` suffix needed. """
        logical_id = dehyphenate(self.name.logical_id(suffix)).replace('_', '')
        return Secret(
            logical_id,
            Name=logical_id,
            Description=description,
            SecretString='PLACEHOLDER',  # populate post-deploy via aws secretsmanager put-secret-value
            Tags=self.tags.cost_tag_array()
        )

    def falcon_cid_secret(self) -> Secret:
        return self._falcon_stub_secret(
            self.FALCON_CID_LOGICAL_SUFFIX,
            'Crowdstrike Falcon Customer ID (CID). Used by the falcon sensor sidecar at runtime.'
        )

    def falcon_client_id_secret(self) -> Secret:
        return self._falcon_stub_secret(
            self.FALCON_CLIENT_ID_LOGICAL_SUFFIX,
            'Crowdstrike Falcon API Client ID. Used when calling the Falcon API to download '
            'the sensor or register hosts.'
        )

    def falcon_client_secret_secret(self) -> Secret:
        return self._falcon_stub_secret(
            self.FALCON_CLIENT_SECRET_LOGICAL_SUFFIX,
            'Crowdstrike Falcon API Client Secret (paired with FALCON_CLIENT_ID).'
        )

    def output_simple_secret_arn(self, secret: Secret, export_name: str, description: str) -> Output:
        """ Output a Secrets Manager secret's ARN under EXPORTS so other stacks can ImportValue it.
            Ref(secret) returns the secret's ARN for AWS::SecretsManager::Secret. """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description=description,
            Value=Ref(secret),
            Export=self.EXPORTS.export(export_name)
        )
