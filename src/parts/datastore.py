import os
import json
import re
import subprocess

from dcicutils.misc_utils import dict_zip
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
from troposphere.rds import DBInstance, DBParameterGroup, DBSubnetGroup
from troposphere.secretsmanager import Secret, GenerateSecretString, SecretTargetAttachment
from troposphere.sqs import Queue
from troposphere.s3 import Bucket, Private
from troposphere.kms import Key
from dcicutils.env_utils import prod_bucket_env
from dcicutils.misc_utils import as_seconds
from src.constants import (
    # ACCOUNT_NUMBER,
    DEPLOYING_IAM_USER, ENV_NAME,
    S3_BUCKET_ORG,
    # S3_ENCRYPT_KEY,
    # RDS_AZ,
    RDS_DB_NAME, RDS_DB_PORT, RDS_STORAGE_SIZE, RDS_INSTANCE_SIZE,
    ES_DATA_TYPE, ES_DATA_COUNT,
    # ES_MASTER_COUNT, ES_MASTER_TYPE,
    ES_VOLUME_SIZE
)
from src.exports import C4Exports
from src.part import C4Part
from src.parts.network import C4NetworkExports
from ..base import ConfigManager


class C4DatastoreExports(C4Exports):
    """ Holds datastore export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = 'ExportElasticSearchURL'

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
    APPLICATION_METADATA_BUNDLES_BUCKET = 'ExportAppMetadataBundlesBucket'
    APPLICATION_TIBANNA_LOGS_BUCKET = 'ExportAppTibannaLogsBucket'

    # Output SQS Queues
    APPLICATION_INDEXER_PRIMARY_QUEUE = 'ExportApplicationIndexerPrimaryQueue'
    APPLICATION_INDEXER_SECONDAY_QUEUE = 'ExportApplicationIndexerSecondaryQueue'
    APPLICATION_INDEXER_DLQ = 'ExportApplicationIndexerDLQ'
    APPLICATION_INGESTION_QUEUE = 'ExportApplicationIngestionQueue'
    APPLICATION_INDEXER_REALTIME_QUEUE = 'ExportApplicationIndexerRealtimeQueue'  # unused

    # e.g., name will be C4DatastoreTrialAlphaExportElasticSearchURL
    #       or might not contain '...Alpha...'
    _ES_URL_EXPORT_PATTERN = re.compile('.*Datastore.*ElasticSearchURL.*')

    @classmethod
    def get_es_url(cls):
        return ConfigManager.find_stack_output(cls._ES_URL_EXPORT_PATTERN.match, value_only=True)

    # e.g., name will be C4DatastoreTrialAlphaExportFoursightEnvsBucket
    #       or might not contain '...Alpha...'
    _ENVS_BUCKET_EXPORT_PATTERN = re.compile(".*Datastore.*EnvsBucket")

    @classmethod
    def get_envs_bucket(cls):
        return ConfigManager.find_stack_output(cls._ENVS_BUCKET_EXPORT_PATTERN.match, value_only=True)

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
        C4DatastoreExports.APPLICATION_BLOBS_BUCKET: ConfigManager.AppBucketTemplate.BLOBS,
        C4DatastoreExports.APPLICATION_FILES_BUCKET: ConfigManager.AppBucketTemplate.FILES,
        C4DatastoreExports.APPLICATION_WFOUT_BUCKET: ConfigManager.AppBucketTemplate.WFOUT,
        C4DatastoreExports.APPLICATION_SYSTEM_BUCKET: ConfigManager.AppBucketTemplate.SYSTEM,
        C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET: ConfigManager.AppBucketTemplate.METADATA_BUNDLES,
        C4DatastoreExports.APPLICATION_TIBANNA_LOGS_BUCKET: ConfigManager.AppBucketTemplate.TIBANNA_LOGS,

    }

    @classmethod
    def application_layer_bucket(cls, export_name):
        bucket_name_template = cls.APPLICATION_LAYER_BUCKETS[export_name]
        bucket_name = cls.resolve_bucket_name(bucket_name_template)
        return bucket_name

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)

    # FOURSIGHT_LAYER_PREFIX = 'foursight-{org_prefix}{env_name}'

    FOURSIGHT_LAYER_BUCKETS = {
        C4DatastoreExports.FOURSIGHT_ENV_BUCKET: ConfigManager.FSBucketTemplate.ENVS,
        C4DatastoreExports.FOURSIGHT_RESULT_BUCKET: ConfigManager.FSBucketTemplate.RESULTS,
        C4DatastoreExports.FOURSIGHT_APPLICATION_VERSION_BUCKET: ConfigManager.FSBucketTemplate.APPLICATION_VERSIONS,
    }

    @classmethod
    def foursight_layer_bucket(cls, export_name):
        bucket_name_template = cls.FOURSIGHT_LAYER_BUCKETS[export_name]
        bucket_name = cls.resolve_bucket_name(bucket_name_template)
        return bucket_name

    @classmethod
    def resolve_bucket_name(cls, bucket_template):
        return ConfigManager.resolve_bucket_name(bucket_template)

        # """
        # Resolves a bucket_template into a bucket_name (presuming an appropriate os.environ).
        # The ENCODED_BS_ENV and ENCODED_S3_BUCKET_ORG environment variables are expected to be in place at time of call.
        # """
        # # NOTE: In legacy CGAP, we'd want to be looking at S3_BUCKET_ENV, which did some backflips to address
        # #       the naming for foursight (including uses of prod_bucket_env), so that webprod was still used
        # #       even after we changed to blue/green, but unless we're trying to make this deployment procedure
        # #       cover that special case, it should suffice (and use fewer environment variables) to only worry
        # #       about ENV_NAME. -kmp 24-Jun-2021
        # env_name = env_name or os.environ[ENV_NAME]
        # org_name = org_name or os.environ.get(S3_BUCKET_ORG)  # Result is allowed to be missing or empty if none desired.
        # org_prefix = (org_name + "-") if org_name else ""
        # bucket_name = bucket_template.format(env_name=env_name, org_prefix=org_prefix)
        # # print(bucket_template,"=>",bucket_name)
        # return bucket_name

    # Contains application configuration template, written to secrets manager
    # NOTE: this configuration is NOT valid by default - it must be manually updated
    # with values not available at orchestration time.
    # TODO only use configuration placeholder for orchestration time values; otherwise, use src.constants values
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'

    def add_placeholders(cls, template):
        return {
            k: cls.CONFIGURATION_PLACEHOLDER if v is None else v
            for k, v in template.items()
        }

    def application_configuration_template(cls):
        env_name = os.environ.get(ENV_NAME)
        # print("ENV_NAME=", repr(ENV_NAME))
        # print("env_name=", repr(env_name))
        result = cls.add_placeholders({
            'deploying_iam_user': os.environ.get(DEPLOYING_IAM_USER),
            'Auth0Client': None,
            'Auth0Secret': None,
            'ENV_NAME': env_name,
            'ENCODED_BS_ENV': env_name,
            'ENCODED_DATA_SET': 'prod',
            'ENCODED_ES_SERVER': None,
            'ENCODED_FILE_UPLOAD_BUCKET': cls.application_layer_bucket(C4DatastoreExports.APPLICATION_FILES_BUCKET),
            'ENCODED_FILE_WFOUT_BUCKET': cls.application_layer_bucket(C4DatastoreExports.APPLICATION_WFOUT_BUCKET),
            'ENCODED_BLOB_BUCKET': cls.application_layer_bucket(C4DatastoreExports.APPLICATION_BLOBS_BUCKET),
            'ENCODED_SYSTEM_BUCKET': cls.application_layer_bucket(C4DatastoreExports.APPLICATION_SYSTEM_BUCKET),
            'ENCODED_METADATA_BUNDLES_BUCKET': cls.application_layer_bucket(C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET),
            'LANG': 'en_US.UTF-8',
            'LC_ALL': 'en_US.UTF-8',
            'RDS_HOSTNAME': None,
            'RDS_DB_NAME': os.environ.get(RDS_DB_NAME) or cls.DEFAULT_RDS_DB_NAME,
            'RDS_PORT': os.environ.get(RDS_DB_PORT) or cls.DEFAULT_RDS_PORT,
            'RDS_USERNAME': 'postgresql',
            'RDS_PASSWORD': None,
            'S3_ENCRYPT_KEY': None,
            # 'S3_BUCKET_ENV': env_name,  # NOTE: not prod_bucket_env(env_name); see notes in resolve_bucket_name
            'ENCODED_S3_BUCKET_ORG': os.environ.get(S3_BUCKET_ORG),
            'SENTRY_DSN': "",
            'reCaptchaKey': None,
            'reCaptchaSecret': None,
            'S3_AWS_ACCESS_KEY_ID': None,
            'S3_AWS_SECRET_ACCESS_KEY': None,
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
        template.add_resource(self.application_configuration_secret())

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

    @staticmethod
    def build_s3_bucket(bucket_name, access_control=Private) -> Bucket:
        """ Creates an S3 bucket under the given name/access control permissions.
            See troposphere.s3 for access control options.
        """
        bucket_name_parts = bucket_name.split('-')
        return Bucket(
            ''.join(bucket_name_parts),  # Name != BucketName
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
        logical_id = self.name.logical_id(self.RDS_SECRET_STRING)
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
        deploying_iam_user = os.environ.get(DEPLOYING_IAM_USER)
        env_identifier = os.environ.get(ENV_NAME).replace('-', '')
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
                            Join('', ['arn:aws:iam::', AccountId, ':user/', os.environ.get(DEPLOYING_IAM_USER)]),
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
        env_identifier = os.environ.get(ENV_NAME).replace('-', '')
        if not env_identifier:
            raise Exception('Did not set required key in .env! Should never get here.')
        logical_id = self.name.logical_id(self.APPLICATION_SECRET_STRING) + env_identifier
        return Secret(
            logical_id,
            Name=logical_id,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(self.application_configuration_template()),
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

    def rds_instance(self, instance_size='db.t3.medium',
                     az_zone='us-east-1a', storage_size=20, storage_type='standard',
                     db_name='ebdb', postgres_version='12.6') -> DBInstance:
        """ Returns the single RDS instance for the infrastructure stack. """
        logical_id = self.name.logical_id('RDS%s') % os.environ.get(ENV_NAME, '').replace('-', '')
        secret_string_logical_id = self.name.logical_id(self.RDS_SECRET_STRING)
        return DBInstance(
            logical_id,
            AllocatedStorage=os.environ.get(RDS_STORAGE_SIZE) or storage_size,
            DBInstanceClass=os.environ.get(RDS_INSTANCE_SIZE) or instance_size,
            Engine='postgres',
            EngineVersion=postgres_version,
            DBInstanceIdentifier=logical_id,
            DBName=os.environ.get(RDS_DB_NAME) or db_name,
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
        domain_id_token = 'ES%s' % os.environ.get(ENV_NAME, '').replace('-', '')
        logical_id = self.name.logical_id(domain_id_token)
        domain_name = self.name.domain_name(domain_id_token)
        options = {}
        try:  # feature not yet supported by troposphere
            options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
        except NotImplementedError:
            pass
        # account_num = os.environ.get(ACCOUNT_NUMBER)
        return Domain(
            logical_id,
            DomainName=domain_name,
            NodeToNodeEncryptionOptions=NodeToNodeEncryptionOptions(Enabled=True),
            EncryptionAtRestOptions=EncryptionAtRestOptions(Enabled=True),  # TODO specify KMS key
            ElasticsearchClusterConfig=ElasticsearchClusterConfig(
                InstanceCount=os.environ.get(ES_DATA_COUNT) or number_of_data_nodes,
                InstanceType=os.environ.get(ES_DATA_TYPE) or data_node_instance_type,
            ),
            ElasticsearchVersion='6.8',
            EBSOptions=EBSOptions(
                EBSEnabled=True,
                VolumeSize=os.environ.get(ES_VOLUME_SIZE, 10),
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
        cgap_env = os.environ.get(ENV_NAME)
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
