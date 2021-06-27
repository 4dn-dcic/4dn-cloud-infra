import os
import json
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
from dcicutils.misc_utils import as_seconds
from src.constants import (
    ACCOUNT_NUMBER,
    DEPLOYING_IAM_USER, ENV_NAME,
    S3_BUCKET_ORG,
    # RDS_AZ,
    RDS_DB_NAME, RDS_STORAGE_SIZE, RDS_INSTANCE_SIZE,
    ES_DATA_TYPE, ES_DATA_COUNT,
    # ES_MASTER_COUNT, ES_MASTER_TYPE,
    ES_VOLUME_SIZE
)
from src.exports import C4Exports
from src.part import C4Part
from src.parts.network import C4NetworkExports


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

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce amount
        # of manual configuration
        parameter = 'DatastoreStackNameParameter'
        super().__init__(parameter)


class C4Datastore(C4Part):
    """ Defines the datastore stack - see resources created in build_template method. """
    APPLICATION_SECRET_STRING = 'ApplicationConfiguration'
    RDS_SECRET_STRING = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4DatastoreExports()
    NETWORK_EXPORTS = C4NetworkExports()

    POSTGRES_VERSION = '12'

    # Buckets used by the Application layer we need to initialize as part of the datastore
    # Intended to be .formatted with the deploying env_name
    APPLICATION_LAYER_BUCKETS = {
        'application-blobs': 'application-{org_prefix}{env_name}-blobs',
        'application-files': 'application-{org_prefix}{env_name}-files',
        'application-wfout': 'application-{org_prefix}{env_name}-wfout',
        'application-system': 'application-{org_prefix}{env_name}-system',
        'application-metadata-bundles': 'application-{org_prefix}{env_name}-metadata-bundles',
        'application-tibanna-logs': 'application-{org_prefix}{env_name}-tibanna-logs'
    }

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)
    FOURSIGHT_LAYER_BUCKETS = {
        'foursight-envs': 'foursight-{org_prefix}{env_name}-envs',
        'foursight-results': 'foursight-{org_prefix}{env_name}-results',
        'foursight-application-versions': 'foursight-{org_prefix}{env_name}-application-versions'
    }

    # Contains application configuration template, written to secrets manager
    # NOTE: this configuration is NOT valid by default - it must be manually updated
    # with values not available at orchestration time.
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
        'RDS_HOSTNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_DB_NAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PORT': CONFIGURATION_DEFAULT_RDS_PORT,
        'RDS_USERNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PASSWORD': CONFIGURATION_PLACEHOLDER,
        'S3_ENCRYPT_KEY': CONFIGURATION_PLACEHOLDER,
        # 'S3_BUCKET_ENV': CONFIGURATION_PLACEHOLDER,
        'S3_BUCKET_ORG': CONFIGURATION_PLACEHOLDER,
        'SENTRY_DSN': CONFIGURATION_PLACEHOLDER,
        'reCaptchaKey': CONFIGURATION_PLACEHOLDER,
        'reCaptchaSecret': CONFIGURATION_PLACEHOLDER,
    }

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
        template.add_resource(self.s3_encrypt_key())
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
        for export_name, bucket_template in dict_zip(
                {
                    'application-blobs': C4DatastoreExports.APPLICATION_BLOBS_BUCKET,
                    'application-files': C4DatastoreExports.APPLICATION_FILES_BUCKET,
                    'application-wfout': C4DatastoreExports.APPLICATION_WFOUT_BUCKET,
                    'application-system': C4DatastoreExports.APPLICATION_SYSTEM_BUCKET,
                    'application-metadata-bundles': C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET,
                    'application-tibanna-logs': C4DatastoreExports.APPLICATION_TIBANNA_LOGS_BUCKET,
                    'foursight-envs': C4DatastoreExports.FOURSIGHT_ENV_BUCKET,
                    'foursight-results': C4DatastoreExports.FOURSIGHT_RESULT_BUCKET,
                    'foursight-application-versions': C4DatastoreExports.FOURSIGHT_APPLICATION_VERSION_BUCKET
                },
                dict(self.APPLICATION_LAYER_BUCKETS, **self.FOURSIGHT_LAYER_BUCKETS)):

            org_name = os.environ.get(S3_BUCKET_ORG)
            # NOTE: In legacy CGAP, we'd want to be looking at S3_BUCKET_ENV, which did some backflips to address
            #       the naming for foursight, so that webprod was still used even after we changed to blue/green,
            #       but unless we're trying to make this deployment procedure cover that special case, it should
            #       suffice (and use fewer environment variables) to only worry about ENV_NAME. -kmp 24-Jun-2021
            env_name = os.environ.get(ENV_NAME)
            org_prefix = (org_name + "-") if org_name else ""
            bucket_name = bucket_template.format(env_name=env_name, org_prefix=org_prefix)
            bucket = self.build_s3_bucket(bucket_name)
            template.add_resource(bucket)
            template.add_output(self.output_s3_bucket(export_name, bucket_name))

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
            SecretString=json.dumps(self.APPLICATION_CONFIGURATION_TEMPLATE),
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
        account_num = os.environ.get(ACCOUNT_NUMBER)
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
