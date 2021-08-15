import json
import re

from dcicutils.misc_utils import as_seconds
from troposphere import (
    Join, Ref, Template, Tags, Parameter, Output, GetAtt,
    AccountId
)
from troposphere.elasticsearch import (
    Domain, ElasticsearchClusterConfig,
    EBSOptions, EncryptionAtRestOptions, NodeToNodeEncryptionOptions, VPCOptions
)
try:
    from troposphere.elasticsearch import DomainEndpointOptions  # noQA
except ImportError:
    def DomainEndpointOptions(*args, **kwargs):  # noQA
        raise NotImplementedError('DomainEndpointOptions')
from troposphere.kms import Key
from troposphere.rds import DBInstance, DBParameterGroup, DBSubnetGroup
from troposphere.s3 import Bucket, Private
from troposphere.secretsmanager import Secret, GenerateSecretString, SecretTargetAttachment
from troposphere.sqs import Queue
from ..base import ConfigManager, exportify, COMMON_STACK_PREFIX, camelize, dehyphenate
from ..constants import Settings, Secrets
from ..exports import C4Exports
from ..part import C4Part
from ..parts.network import C4NetworkExports


class C4DatastoreExports(C4Exports):
    """ Holds datastore export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = exportify('ElasticSearchURL')

    # RDS Exports
    RDS_URL = exportify('RdsUrl')
    RDS_PORT = exportify('RdsPort')

    # Output secrets info
    APPLICATION_CONFIGURATION_SECRET_NAME = exportify("ApplicationConfigurationSecretName")

    # Output env bucket and result bucket
    FOURSIGHT_ENV_BUCKET = exportify('FoursightEnvBucket')
    FOURSIGHT_RESULT_BUCKET = exportify('FoursightResultBucket')
    FOURSIGHT_APPLICATION_VERSION_BUCKET = exportify('FoursightApplicationVersionBucket')

    # Output production S3 bucket information
    APPLICATION_SYSTEM_BUCKET = exportify('AppSystemBucket')
    APPLICATION_WFOUT_BUCKET = exportify('AppWfoutBucket')
    APPLICATION_FILES_BUCKET = exportify('AppFilesBucket')
    APPLICATION_BLOBS_BUCKET = exportify('AppBlobsBucket')
    APPLICATION_METADATA_BUNDLES_BUCKET = exportify('AppMetadataBundlesBucket')
    APPLICATION_TIBANNA_LOGS_BUCKET = exportify('AppTibannaLogsBucket')

    # Output SQS Queues
    APPLICATION_INDEXER_PRIMARY_QUEUE = exportify('ApplicationIndexerPrimaryQueue')
    APPLICATION_INDEXER_SECONDAY_QUEUE = exportify('ApplicationIndexerSecondaryQueue')
    APPLICATION_INDEXER_DLQ = exportify('ApplicationIndexerDLQ')
    APPLICATION_INGESTION_QUEUE = exportify('ApplicationIngestionQueue')
    APPLICATION_INDEXER_REALTIME_QUEUE = exportify('ApplicationIndexerRealtimeQueue')  # unused

    # e.g., name will be C4DatastoreTrialAlphaExportElasticSearchURL
    #       or might not contain '...Alpha...'
    _ES_URL_EXPORT_PATTERN = re.compile(f'.*Datastore.*{ES_URL}.*')
    # _ES_URL_EXPORT_PATTERN = re.compile('.*Datastore.*ElasticSearchURL.*')

    @classmethod
    def get_es_url(cls):
        return ConfigManager.find_stack_output(cls._ES_URL_EXPORT_PATTERN.match, value_only=True)

    # e.g., name will be C4DatastoreTrialAlphaExportFoursightEnvBucket
    #       or might not contain '...Alpha...'
    # Also, name change in progress from EnvsBucket turning to EnvBucket, so match both
    _ENV_BUCKET_EXPORT_PATTERN = re.compile(".*Datastore.*Env.*Bucket")

    @classmethod
    def get_env_bucket(cls):
        return ConfigManager.find_stack_output(cls._ENV_BUCKET_EXPORT_PATTERN.match, value_only=True)

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce amount
        # of manual configuration
        parameter = 'DatastoreStackNameParameter'
        super().__init__(parameter)


class C4Datastore(C4Part):
    """ Defines the datastore stack - see resources created in build_template method. """
    APPLICATION_SECRET_STRING = 'ApplicationConfiguration'
    DEFAULT_RDS_DB_NAME = 'ebdb'
    DEFAULT_RDS_PORT = '5432'
    RDS_SECRET_STRING = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4DatastoreExports()
    NETWORK_EXPORTS = C4NetworkExports()

    POSTGRES_VERSION = '12'

    # Buckets used by the Application layer we need to initialize as part of the datastore
    # Intended to be .formatted with the deploying env_name

    APPLICATION_LAYER_BUCKETS = {
        C4DatastoreExports.APPLICATION_BLOBS_BUCKET: ConfigManager.get_app_bucket_template('BLOBS'),
        C4DatastoreExports.APPLICATION_FILES_BUCKET: ConfigManager.get_app_bucket_template('FILES'),
        C4DatastoreExports.APPLICATION_WFOUT_BUCKET: ConfigManager.get_app_bucket_template('WFOUT'),
        C4DatastoreExports.APPLICATION_SYSTEM_BUCKET: ConfigManager.get_app_bucket_template('SYSTEM'),
        C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET:
            ConfigManager.get_app_bucket_template('METADATA_BUNDLES'),
        C4DatastoreExports.APPLICATION_TIBANNA_LOGS_BUCKET: ConfigManager.get_app_bucket_template('TIBANNA_LOGS'),
    }

    @classmethod
    def application_layer_bucket(cls, export_name):
        bucket_name_template = cls.APPLICATION_LAYER_BUCKETS[export_name]
        bucket_name = cls.resolve_bucket_name(bucket_name_template)
        return bucket_name

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)

    # FOURSIGHT_LAYER_PREFIX = '{foursight_prefix}{env_name}'

    FOURSIGHT_LAYER_BUCKETS = {
        C4DatastoreExports.FOURSIGHT_ENV_BUCKET: ConfigManager.get_fs_bucket_template('ENVS'),
        C4DatastoreExports.FOURSIGHT_RESULT_BUCKET: ConfigManager.get_fs_bucket_template('RESULTS'),
        C4DatastoreExports.FOURSIGHT_APPLICATION_VERSION_BUCKET:
            ConfigManager.get_fs_bucket_template('APPLICATION_VERSIONS'),
    }

    @classmethod
    def foursight_layer_bucket(cls, export_name):
        bucket_name_template = cls.FOURSIGHT_LAYER_BUCKETS[export_name]
        bucket_name = cls.resolve_bucket_name(bucket_name_template)
        return bucket_name

    @classmethod
    def resolve_bucket_name(cls, bucket_template):
        """
        Resolves a bucket_template into a bucket_name.
        """
        return ConfigManager.resolve_bucket_name(bucket_template)

    # Contains application configuration template, written to secrets manager
    # NOTE: this configuration is NOT valid by default - it must be manually updated
    # with values not available at orchestration time.
    # TODO only use configuration placeholder for orchestration time values; otherwise, use src.constants values
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    @classmethod
    def add_placeholders(cls, template):
        return {
            k: cls.CONFIGURATION_PLACEHOLDER if v is None else v
            for k, v in template.items()
        }

    @classmethod
    def application_configuration_template(cls):
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        # print("ENV_NAME=", repr(ENV_NAME))
        # print("env_name=", repr(env_name))
        result = cls.add_placeholders({
            'deploying_iam_user': ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER),  # required
            'AWS_ACCESS_KEY_ID': None,
            'AWS_SECRET_ACCESS_KEY': None,
            'Auth0Client': ConfigManager.get_config_secret(Secrets.AUTH0_CLIENT, default=None),
            'Auth0Secret': ConfigManager.get_config_secret(Secrets.AUTH0_SECRET, default=None),
            'ENV_NAME': env_name,
            'ENCODED_APPLICATION_BUCKET_PREFIX': cls.resolve_bucket_name("{application_prefix}"),
            'ENCODED_BS_ENV': env_name,
            'ENCODED_DATA_SET': 'prod',
            'ENCODED_ES_SERVER':  C4DatastoreExports.get_es_url(), # None,
            'ENCODED_FOURSIGHT_BUCKET_PREFIX': cls.resolve_bucket_name("{foursight_prefix}"),
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
            'RDS_DB_NAME': ConfigManager.get_config_setting(Settings.RDS_DB_NAME, cls.DEFAULT_RDS_DB_NAME),
            'RDS_PORT': ConfigManager.get_config_setting(Settings.RDS_DB_PORT, cls.DEFAULT_RDS_PORT),
            'RDS_USERNAME': 'postgresql',
            'RDS_PASSWORD': None,
            'S3_ENCRYPT_KEY': ConfigManager.get_config_setting(Secrets.S3_ENCRYPT_KEY,
                                                               ConfigManager.get_s3_encrypt_key_from_file()),
            # 'S3_BUCKET_ENV': env_name,  # NOTE: not prod_bucket_env(env_name); see notes in resolve_bucket_name
            'SENTRY_DSN': "",
            'reCaptchaKey': ConfigManager.get_config_secret(Secrets.RECAPTCHA_KEY, default=None),
            'reCaptchaSecret': ConfigManager.get_config_secret(Secrets.RECAPTCHA_SECRET, default=None),
        })
        # print("application_configuration_template() => %s" % json.dumps(result, indent=2))
        return result

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # Adds RDS primitives
        for i in [self.rds_secret(), self.rds_parameter_group(),
                  self.rds_subnet_group(), self.rds_secret_attachment()]:
            template.add_resource(i)

        # Add RDS itself + Outputs
        rds = self.rds_instance()
        template.add_resource(rds)
        template.add_output(self.output_rds_url(rds))
        template.add_output(self.output_rds_port(rds))

        # Adds Elasticsearch + Outputs
        es = self.elasticsearch_instance()
        template.add_resource(es)
        template.add_output(self.output_es_url(es))

        # Add S3_ENCRYPT_KEY, application configuration template
        # template.add_resource(self.s3_encrypt_key())
        secret = self.application_configuration_secret()
        template.add_resource(secret)
        template.add_output(
            self.output_application_configuration_secret_name(
                C4DatastoreExports.APPLICATION_CONFIGURATION_SECRET_NAME,
                secret))

        # Adds SQS Queues + Outputs
        for export_name, i in [(C4DatastoreExports.APPLICATION_INDEXER_PRIMARY_QUEUE, self.primary_queue()),
                               (C4DatastoreExports.APPLICATION_INDEXER_SECONDAY_QUEUE, self.secondary_queue()),
                               (C4DatastoreExports.APPLICATION_INDEXER_DLQ, self.dead_letter_queue()),
                               (C4DatastoreExports.APPLICATION_INGESTION_QUEUE, self.ingestion_queue()),
                               (C4DatastoreExports.APPLICATION_INDEXER_REALTIME_QUEUE, self.realtime_queue())]:
            template.add_resource(i)
            template.add_output(self.output_sqs_instance(export_name, i))

        # Add/Export S3 buckets

        def add_and_export_s3_bucket(export_name, bucket_template):
            bucket_name = self.resolve_bucket_name(bucket_template)
            bucket = self.build_s3_bucket(bucket_name)
            template.add_resource(bucket)
            template.add_output(self.output_s3_bucket(export_name, bucket_name))

        for export_name, bucket_template in self.APPLICATION_LAYER_BUCKETS.items():
            add_and_export_s3_bucket(export_name, bucket_template)
        for export_name, bucket_template in self.FOURSIGHT_LAYER_BUCKETS.items():
            add_and_export_s3_bucket(export_name, bucket_template)

        return template

    @classmethod
    def build_s3_bucket_resource_name(cls, bucket_name):
        # bucket_name_parts = bucket_name.split('-')
        # resource_name = ''.join(bucket_name_parts),  # Name != BucketName
        res = camelize(COMMON_STACK_PREFIX + 'bucket-' + bucket_name)
        print(f"bucket {bucket_name} => {res}")
        return res

    @classmethod
    def build_s3_bucket(cls, bucket_name, access_control=Private) -> Bucket:
        """ Creates an S3 bucket under the given name/access control permissions.
            See troposphere.s3 for access control options.
        """
        # bucket_name_parts = bucket_name.split('-')
        return Bucket(
            # ''.join(bucket_name_parts),  # Name != BucketName
            cls.build_s3_bucket_resource_name(bucket_name),
            BucketName=bucket_name,
            AccessControl=access_control
        )

    def output_s3_bucket(self, export_name, bucket_name: str) -> Output:
        """ Builds an output for the given export_name/Bucket resource """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='S3 Bucket name for: %s' % export_name,
            Value=bucket_name,
            Export=self.EXPORTS.export(export_name)
        )

    def rds_secret(self) -> Secret:
        """ Returns the RDS secret, as generated and stored by AWS Secrets Manager """
        logical_id = self.name.logical_id(self.RDS_SECRET_STRING, context='rds_secret')
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This is the RDS instance master password',
            GenerateSecretString=GenerateSecretString(
                SecretStringTemplate='{"username":"postgresql"}',
                GenerateStringKey='password',
                PasswordLength=30,
                ExcludePunctuation=True,
            ),
            Tags=self.tags.cost_tag_array(),
        )

    def s3_encrypt_key(self) -> Key:
        """ Uses AWS KMS to generate an AES-256 GCM Encryption Key for encryption when
            uploading sensitive information to S3. This value should be written to the
            application configuration and also passed to Foursight/Tibanna.

            TODO: implement APIs to use this key correctly, cannot download/distribute from KMS
            Note that when doing this, the KeyPolicy will need to be updated
        """
        deploying_iam_user = ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER)  # Required config setting
        env_identifier = ConfigManager.get_config_setting(Settings.ENV_NAME).replace('-', '')
        if not deploying_iam_user or not env_identifier:
            raise Exception('Did not set required key in .env! Should never get here.')
        logical_id = self.name.logical_id('S3ENCRYPTKEY') + env_identifier
        return Key(
            logical_id,
            Description='Key for encrypting sensitive S3 files for CGAP Ecosystem',
            KeyPolicy={
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'Enable IAM Policies',
                    'Effect': 'Allow',
                    'Principal': {
                        'AWS': [
                            Join('', ['arn:aws:iam::', AccountId, ':user/', deploying_iam_user]),
                        ]
                    },
                    'Action': 'kms:*',  # XXX: constrain further?
                    'Resource': '*'
                }]
            },
            KeySpec='SYMMETRIC_DEFAULT',  # (AES-256-GCM)
            Tags=self.tags.cost_tag_array()
        )

    def application_configuration_secret(self) -> Secret:
        """ Returns the application configuration secret. Note that this pushes up just a
            template - you must fill it out according to the specification in the README.
        """
        env_identifier = camelize(ConfigManager.get_config_setting(Settings.ENV_NAME))
        logical_id = self.name.logical_id(self.APPLICATION_SECRET_STRING) + env_identifier
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(self.application_configuration_template(),indent=2),
            Tags=self.tags.cost_tag_array()
        )

    def rds_subnet_group(self) -> DBSubnetGroup:
        """ Returns a subnet group for the single RDS instance in the infrastructure stack """
        logical_id = self.name.logical_id('DBSubnetGroup')
        return DBSubnetGroup(
            logical_id,
            DBSubnetGroupDescription='RDS subnet group',
            SubnetIds=[
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
            ],
            Tags=self.tags.cost_tag_array(),
        )

    def rds_instance_name(self, env_name):
        camelized = camelize(env_name)
        return f"RDSfor{camelized}"

    def rds_instance(self, instance_size='db.t3.medium',
                     az_zone='us-east-1a', storage_size=20, storage_type='standard',
                     db_name='ebdb', postgres_version='12.6') -> DBInstance:
        """ Returns the single RDS instance for the infrastructure stack. """
        # logical_id = self.name.logical_id('RDS%s') % ConfigManager.get_config_setting(Settings.ENV_NAME, '').replace('-', '')
        logical_id = self.name.logical_id(self.rds_instance_name(ConfigManager.get_config_setting(Settings.ENV_NAME)))
        secret_string_logical_id = self.name.logical_id(self.RDS_SECRET_STRING)
        return DBInstance(
            logical_id,
            AllocatedStorage=ConfigManager.get_config_setting(Settings.RDS_STORAGE_SIZE, storage_size),
            DBInstanceClass=ConfigManager.get_config_setting(Settings.RDS_INSTANCE_SIZE, instance_size),
            Engine='postgres',
            EngineVersion=postgres_version,
            DBInstanceIdentifier=logical_id,
            DBName=ConfigManager.get_config_setting(Settings.RDS_DB_NAME, db_name),
            DBParameterGroupName=Ref(self.rds_parameter_group()),
            DBSubnetGroupName=Ref(self.rds_subnet_group()),
            StorageEncrypted=True,  # TODO use KmsKeyId to configure KMS key (requires db replacement)
            CopyTagsToSnapshot=True,
            AvailabilityZone=az_zone,
            PubliclyAccessible=False,
            StorageType=storage_type,
            VPCSecurityGroups=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.DB_SECURITY_GROUP)],
            MasterUsername=Join('', [
                '{{resolve:secretsmanager:',
                {'Ref': secret_string_logical_id},
                ':SecretString:username}}'
            ]),
            MasterUserPassword=Join('', [
                '{{resolve:secretsmanager:',
                {'Ref': secret_string_logical_id},
                ':SecretString:password}}'
            ]),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

#     def rds_password(self, resource: DBInstance) -> str:
#         import pdb; pdb.set_trace()
#         return GetAtt(resource, 'Endpoint.Password')

    def output_rds_url(self, resource: DBInstance) -> Output:
        """ Outputs RDS URL """
        export_name = C4DatastoreExports.RDS_URL
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='RDS URL for this environment',
            Value=GetAtt(resource, 'Endpoint.Address'),
            Export=self.EXPORTS.export(export_name)
        )

    def output_rds_port(self, resource: DBInstance) -> Output:
        """ Outputs RDS Port """
        export_name = C4DatastoreExports.RDS_PORT
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='RDS Port for this environment',
            Value=GetAtt(resource, 'Endpoint.Port'),
            Export=self.EXPORTS.export(export_name)
        )

    def rds_parameter_group(self) -> DBParameterGroup:
        """ Creates the parameter group for an RDS instance """
        parameters = {
            'rds.force_ssl': 1,  # SSL required for all connections when set to 1
        }
        logical_id = self.name.logical_id('RDSParameterGroup')
        return DBParameterGroup(
            logical_id,
            Description='parameters for C4 RDS instances',
            Family='postgres{version}'.format(version=self.POSTGRES_VERSION),
            Parameters=parameters,
        )

    def rds_secret_attachment(self) -> SecretTargetAttachment:
        """ Attaches the rds_secret to the rds_instance. """
        logical_id = self.name.logical_id('SecretRDSInstanceAttachment')
        return SecretTargetAttachment(
            logical_id,
            TargetType='AWS::RDS::DBInstance',
            SecretId=Ref(self.rds_secret()),
            TargetId=Ref(self.rds_instance()),
        )

    def elasticsearch_instance(self, number_of_data_nodes=1, data_node_instance_type='c5.large.elasticsearch'):
        """ Returns an Elasticsearch domain with 1 data node, configurable via data_node_instance_type. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticsearch-domain.html
            TODO allow master node configuration
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(f"ElasticSearch{camelize(env_name)}")
        domain_name = self.name.domain_name(f"es-{dehyphenate(env_name)}")
        options = {}
        try:  # feature not yet supported by troposphere
            options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
        except NotImplementedError:
            pass
        # account_num = ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)
        domain = Domain(
            logical_id,
            DomainName=domain_name,
            NodeToNodeEncryptionOptions=NodeToNodeEncryptionOptions(Enabled=True),
            EncryptionAtRestOptions=EncryptionAtRestOptions(Enabled=True),  # TODO specify KMS key
            ElasticsearchClusterConfig=ElasticsearchClusterConfig(
                InstanceCount=ConfigManager.get_config_setting(Settings.ES_DATA_COUNT, number_of_data_nodes),
                InstanceType=ConfigManager.get_config_setting(Settings.ES_DATA_TYPE, data_node_instance_type),
            ),
            ElasticsearchVersion='6.8',
            EBSOptions=EBSOptions(
                EBSEnabled=True,
                VolumeSize=ConfigManager.get_config_setting(Settings.ES_VOLUME_SIZE, 10),
                VolumeType='gp2',  # gp3?
            ),
            VPCOptions=VPCOptions(
                SecurityGroupIds=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.HTTPS_SECURITY_GROUP),
                ],
                SubnetIds=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                ],
            ),
            Tags=self.tags.cost_tag_array(name=domain_name),
            **options,
        )
        return domain

    def output_es_url(self, resource: Domain) -> Output:
        """ Outputs ES URL """
        export_name = C4DatastoreExports.ES_URL
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='ES URL for this environment',
            Value=GetAtt(resource, 'DomainEndpoint'),
            Export=self.EXPORTS.export(export_name)
        )

    def build_sqs_instance(self, logical_id_suffix, name_suffix, timeout_in_minutes=10) -> Queue:
        """ Builds a SQS instance with the logical id suffix for CloudFormation and the given name_suffix for the queue
            name. Uses 'mastertest' as default cgap env. """
        logical_name = self.name.logical_id(logical_id_suffix)
        cgap_env = ConfigManager.get_config_setting(Settings.ENV_NAME)
        queue_name = 'cgap-{env}-{suffix}'.format(env=cgap_env, suffix=name_suffix)
        return Queue(
            logical_name,
            QueueName=queue_name,
            VisibilityTimeout=as_seconds(minutes=timeout_in_minutes),
            MessageRetentionPeriod=as_seconds(days=14),
            DelaySeconds=1,
            ReceiveMessageWaitTimeSeconds=2,
            Tags=Tags(*self.tags.cost_tag_array(name=queue_name)),  # special case
        )

    def output_application_configuration_secret_name(self, export_name: str, resource: Secret):
        logical_id = self.name.logical_id("ApplicationConfigurationSecretName")
        return Output(
            logical_id,
            Value=Ref(resource.title),
            Description="Name of the application configuration secret",
            Export=self.EXPORTS.export(export_name)
        )

    def output_sqs_instance(self, export_name: str, resource: Queue) -> Output:
        """ Builds an output for SQS """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Description='SQS Endpoint for %s' % export_name,
            Export=self.EXPORTS.export(export_name)
        )

    def primary_queue(self) -> Queue:
        """ MUST MATCH snovault/elasticsearch/indexer_queue.py """
        return self.build_sqs_instance('PrimaryQueue', 'indexer-queue')

    def secondary_queue(self) -> Queue:
        """ MUST MATCH snovault/elasticsearch/indexer_queue.py """
        return self.build_sqs_instance('SecondaryQueue', 'secondary-indexer-queue')

    def dead_letter_queue(self) -> Queue:
        """ MUST MATCH snovault/elasticsearch/indexer_queue.py """
        return self.build_sqs_instance('DeadLetterQueue', 'indexer-queue-dlq')

    def ingestion_queue(self) -> Queue:  # allow 6 hours for ingestion
        """ MUST MATCH cgap-portal/src/encoded/ingestion/queue_utils.py """
        return self.build_sqs_instance('IngestionQueue', 'ingestion-queue', timeout_in_minutes=360)

    def realtime_queue(self) -> Queue:
        return self.build_sqs_instance('RealtimeQueue', 'indexer-queue-realtime')
