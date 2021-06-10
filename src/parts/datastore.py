import os
import json
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
from src.part import C4Part
from src.exports import C4Exports
from src.parts.network import C4NetworkExports
from src.constants import (
    DEPLOYING_IAM_USER, ENV_NAME,
    RDS_AZ, RDS_DB_NAME, RDS_STORAGE_SIZE, RDS_INSTANCE_SIZE,
    ES_DATA_TYPE, ES_DATA_COUNT, ES_MASTER_COUNT, ES_MASTER_TYPE, ES_VOLUME_SIZE
)


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

    # Buckets used by the Application layer we need to initialize as part of the datastore
    # Intended to be .formatted with the deploying env_name
    APPLICATION_LAYER_BUCKETS = [
        'application-{}-blobs',
        'application-{}-files',
        'application-{}-wfout',
        'application-{}-system',
    ]

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)
    FOURSIGHT_LAYER_BUCKETS = [
        'foursight-{}-envs',
        'foursight-{}-results',
        'foursight-{}-application-versions'
    ]

    # Contains application configuration template, written to secrets manager
    # NOTE: this configuration is NOT valid by default - it must be manually updated
    # with values not available at orchestration time.
    CONFIGURATION_PLACEHOLDER = 'XXX: ENTER VALUE'
    APPLICATION_CONFIGURATION_TEMPLATE = {
        'deploying_iam_user': CONFIGURATION_PLACEHOLDER,
        'Auth0Client': CONFIGURATION_PLACEHOLDER,
        'ENV_NAME': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BS_ENV': CONFIGURATION_PLACEHOLDER,
        'ENCODED_DATA_SET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_ES_SERVER': CONFIGURATION_PLACEHOLDER,
        'ENCODED_FILES_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_WFOUT_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_BLOBS_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_SYSTEM_BUCKET': CONFIGURATION_PLACEHOLDER,
        'ENCODED_METADATA_BUNDLE_BUCKET': CONFIGURATION_PLACEHOLDER,
        'LANG': 'en_US.UTF-8',
        'LC_ALL': 'en_US.UTF-8',
        'RDS_HOSTNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_DB_NAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PORT': CONFIGURATION_PLACEHOLDER,
        'RDS_USERNAME': CONFIGURATION_PLACEHOLDER,
        'RDS_PASSWORD': CONFIGURATION_PLACEHOLDER,
        'S3_ENCRYPT_KEY': CONFIGURATION_PLACEHOLDER,
        'SENTRY_DSN': CONFIGURATION_PLACEHOLDER,
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
        # TODO re-enable
        for export_name, bucket_name in zip([C4DatastoreExports.APPLICATION_BLOBS_BUCKET,
                                             C4DatastoreExports.APPLICATION_FILES_BUCKET,
                                             C4DatastoreExports.APPLICATION_WFOUT_BUCKET,
                                             C4DatastoreExports.APPLICATION_SYSTEM_BUCKET,
                                             C4DatastoreExports.FOURSIGHT_ENV_BUCKET,
                                             C4DatastoreExports.FOURSIGHT_RESULT_BUCKET,
                                             C4DatastoreExports.FOURSIGHT_APPLICATION_VERSION_BUCKET],
                                             self.APPLICATION_LAYER_BUCKETS + self.FOURSIGHT_LAYER_BUCKETS):

            env_name = os.environ.get(ENV_NAME)
            bucket = self.build_s3_bucket(bucket_name.format(env_name))
            template.add_resource(bucket)
            template.add_output(self.output_s3_bucket(export_name, bucket_name.format(ENV_NAME)))

        return template

    @staticmethod
    def build_s3_bucket(bucket_name, access_control=Private) -> Bucket:
        """ Creates an S3 bucket under the given name/access control permissions.
            See troposphere.s3 for access control options.
        """
        return Bucket(
            ''.join(bucket_name.split('-')),  # Name != BucketName
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
            Family='postgres11',
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
        logical_id = self.name.logical_id('ES%s' % os.environ.get(ENV_NAME, '').replace('-', ''))
        domain_name = self.name.domain_name(logical_id)
        options = {}
        try:  # feature not yet supported by troposphere
            options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
        except NotImplementedError:
            pass
        return Domain(
            logical_id,
            # DomainName=domain_name,
            # TODO specify DomainName instead of an auto-generated one; ref:
            # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticsearch-domain.html#cfn-elasticsearch-domain-domainname
            AccessPolicies={
                # XXX: this policy needs revising - Will 5/18/21
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Effect': 'Allow',
                        'Principal': {
                            'AWS': [
                                'arn:aws:iam::645819926742:role/aws-elasticbeanstalk-ec2-role',
                                'arn:aws:iam::645819926742:user/will.ronchetti',
                                'arn:aws:iam::645819926742:user/trial.application.user',
                                'arn:aws:iam::645819926742:user/eric.berg'
                            ]
                        },
                        'Action': 'es:*',
                        'Resource': 'arn:aws:es:us-east-1:645819926742:domain/cgaptriales/*'
                    }
                ]
            },
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

    def build_sqs_instance(self, logical_id_suffix, name_suffix) -> Queue:
        """ Builds a SQS instance with the logical id suffix for CloudFormation and the given name_suffix for the queue
            name. Uses 'mastertest' as default cgap env. """
        logical_name = self.name.logical_id(logical_id_suffix)
        cgap_env = os.environ.get(ENV_NAME)
        queue_name = 'cgap-{env}-{suffix}'.format(env=cgap_env, suffix=name_suffix)
        return Queue(
            logical_name,
            QueueName=queue_name,
            VisibilityTimeout=as_seconds(minutes=10),
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
        return self.build_sqs_instance('PrimaryQueue', 'indexer-queue')

    def secondary_queue(self) -> Queue:
        return self.build_sqs_instance('SecondaryQueue', 'indexer-queue-secondary')

    def dead_letter_queue(self) -> Queue:
        return self.build_sqs_instance('DeadLetterQueue', 'indexer-queue-dlq')

    def ingestion_queue(self) -> Queue:
        return self.build_sqs_instance('IngestionQueue', 'ingestion-queue')

    def realtime_queue(self) -> Queue:
        return self.build_sqs_instance('RealtimeQueue', 'indexer-queue-realtime')
