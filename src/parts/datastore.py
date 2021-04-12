from troposphere import Join, Ref, Template, Tags, Parameter, Output, GetAtt
from troposphere.elasticsearch import (Domain, ElasticsearchClusterConfig,
                                       EBSOptions, EncryptionAtRestOptions, NodeToNodeEncryptionOptions, VPCOptions)
try:
    from troposphere.elasticsearch import DomainEndpointOptions  # noQA
except ImportError:
    def DomainEndpointOptions(*args, **kwargs):  # noQA
        raise NotImplementedError('DomainEndpointOptions')
from troposphere.rds import DBInstance, DBParameterGroup, DBSubnetGroup
from troposphere.secretsmanager import Secret, GenerateSecretString, SecretTargetAttachment
from troposphere.sqs import Queue
from troposphere.s3 import Bucket, Private
from dcicutils.misc_utils import as_seconds
from src.part import C4Part
from src.exports import C4Exports
from src.parts.network import C4NetworkExports


class C4DatastoreExports(C4Exports):
    """ Holds datastore export metadata. """
    # Output ES URL for use by foursight/application
    ES_URL = 'ExportElasticSearchURL'

    # TODO add these as needed
    RDS_URL = 'ExportRDSURL'
    RDS_DB = 'ExportRDSDB'
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

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce amount
        # of manual configuration
        parameter = 'DatastoreStackNameParameter'
        super().__init__(parameter)


class C4Datastore(C4Part):
    RDS_SECRET_STRING = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4DatastoreExports()
    NETWORK_EXPORTS = C4NetworkExports()

    # Buckets used by the Application layer we need to initialize as part of the datastore
    # Intended to be .formatted with the deploying env_name
    APPLICATION_LAYER_BUCKETS = [
        'application-{}-system',
        'application-{}-wfout',
        'application-{}-files',
        'application-{}-blobs'
    ]

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)
    FOURSIGHT_LAYER_BUCKETS = [
        'foursight-{}-envs',
        'foursight-{}-results',
        'foursight-{}-application-versions'
    ]

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # Adds RDS
        for i in [self.rds_secret(), self.rds_parameter_group(), self.rds_instance(),
                  self.rds_subnet_group(), self.rds_secret_attachment()]:
            template.add_resource(i)

        # Adds Elasticsearch
        es = self.elasticsearch_instance()
        template.add_resource(es)

        # Adds SQS Queues
        # TODO these probably need outputs as well
        for i in [self.primary_queue(), self.secondary_queue(), self.dead_letter_queue(), self.ingestion_queue(),
                  self.realtime_queue()]:
            template.add_resource(i)

        # TODO Do we want outputs for the buckets here as well?
        for production_bucket_name in self.APPLICATION_LAYER_BUCKETS + self.FOURSIGHT_LAYER_BUCKETS:
            template.add_resource(self.build_s3_bucket(production_bucket_name.format('cgap-mastertest')))

        # TODO Add RDS outputs as needed
        template.add_output(self.output_es_url(es))

        return template

    @staticmethod
    def build_s3_bucket(bucket_name, access_control=Private):
        """ Creates an S3 bucket under the given name/access control permissions.
            See troposphere.s3 for access control options.
        """
        return Bucket(
            ''.join(bucket_name.split('-')),  # Name != BucketName
            BucketName=bucket_name,
            AccessControl=access_control
        )

    def output_s3_bucket(self, export_name, resource: Bucket):
        """ Builds an output for the given export_name/Bucket resource """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='S3 Bucket name: %s' % export_name,
            Value=Ref(resource)
        )

    def rds_secret(self):
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

    def rds_subnet_group(self):
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
                     db_name='ebdb', postgres_version='11.9'):
        """ Returns the single RDS instance for the infrastructure stack. """
        logical_id = self.name.logical_id('RDS')
        secret_string_logical_id = self.name.logical_id(self.RDS_SECRET_STRING)
        return DBInstance(
            logical_id,
            AllocatedStorage=storage_size,
            DBInstanceClass=instance_size,
            Engine='postgres',
            EngineVersion=postgres_version,
            DBInstanceIdentifier=logical_id,
            DBName=db_name,
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
        logical_id = self.name.logical_id('ES')
        domain_name = self.name.domain_name(logical_id)
        options = {}
        try:  # feature not yet supported by troposphere
            options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
        except NotImplementedError:
            pass
        return Domain(
            logical_id,
            DomainName=domain_name,
            AccessPolicies={
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
                InstanceCount=number_of_data_nodes,
                InstanceType=data_node_instance_type,
            ),
            ElasticsearchVersion='6.8',
            EBSOptions=EBSOptions(
                EBSEnabled=True,
                VolumeSize=10,
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

    def output_es_url(self, resource: Domain):
        """ Outputs ES URL """
        export_name = C4DatastoreExports.ES_URL
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='ES URL for this environment',
            Value=GetAtt(resource, 'DomainEndpoint'),
        )

    def build_sqs_instance(self, logical_id_suffix, name_suffix, cgap_env='mastertest') -> Queue:
        """ Builds a SQS instance with the logical id suffix for CloudFormation and the given name_suffix for the queue
            name. Uses 'mastertest' as default cgap env. """
        logical_name = self.name.logical_id(logical_id_suffix)
        queue_name = 'cgap-{env}-{suffix}'.format(env=cgap_env, suffix=name_suffix)  # TODO configurable cgap env
        return Queue(
            logical_name,
            QueueName=queue_name,
            VisibilityTimeout=as_seconds(minutes=10),
            MessageRetentionPeriod=as_seconds(days=14),
            DelaySeconds=1,
            ReceiveMessageWaitTimeSeconds=2,
            Tags=Tags(*self.tags.cost_tag_array(name=queue_name)),  # special case
        )

    def primary_queue(self) -> Queue:
        return self.build_sqs_instance('PrimaryQueue', 'indexer-queue-primary')

    def secondary_queue(self) -> Queue:
        return self.build_sqs_instance('SecondaryQueue', 'indexer-queue-secondary')

    def dead_letter_queue(self) -> Queue:
        return self.build_sqs_instance('DeadLetterQueue', 'indexer-queue-dlq')

    def ingestion_queue(self) -> Queue:
        return self.build_sqs_instance('IngestionQueue', 'ingestion-queue')

    def realtime_queue(self) -> Queue:
        return self.build_sqs_instance('RealtimeQueue', 'indexer-queue-realtime')
