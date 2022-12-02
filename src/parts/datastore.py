import json
import re

from dcicutils.cloudformation_utils import camelize
from dcicutils.misc_utils import as_seconds
from troposphere import (
    Join, Ref, Template, Tags, Parameter, Output, GetAtt,
    AccountId
)
# from troposphere.elasticsearch import (  No longer used post ES7 update
#     Domain, ElasticsearchClusterConfig,
#     EBSOptions, EncryptionAtRestOptions, NodeToNodeEncryptionOptions, VPCOptions
# )
from troposphere.opensearchservice import (
    Domain as OSDomain, ClusterConfig,
    EBSOptions, EncryptionAtRestOptions, NodeToNodeEncryptionOptions, VPCOptions
)
try:
    from troposphere.elasticsearch import DomainEndpointOptions  # noQA
except ImportError:
    def DomainEndpointOptions(*args, **kwargs):  # noQA
        raise NotImplementedError('DomainEndpointOptions')
from troposphere.kms import Key
from troposphere.rds import DBInstance, DBParameterGroup, DBSubnetGroup
from troposphere.s3 import (
    Bucket, BucketEncryption, BucketPolicy, ServerSideEncryptionRule, ServerSideEncryptionByDefault,
    Private, LifecycleConfiguration, LifecycleRule, LifecycleRuleTransition, TagFilter, VersioningConfiguration,
    NoncurrentVersionExpiration, NoncurrentVersionTransition
)
from troposphere.secretsmanager import Secret, GenerateSecretString, SecretTargetAttachment
from troposphere.sqs import Queue
from ..base import ConfigManager, COMMON_STACK_PREFIX
from ..constants import C4DatastoreBase, Settings
from ..exports import C4DatastoreExportsMixin, C4Exports
from ..part import C4Part
from .application_configuration_secrets import ApplicationConfigurationSecrets
from .network import C4NetworkExports
from .iam import C4IAMExports
from ..names import Names


class C4DatastoreExports(C4Exports, C4DatastoreExportsMixin):
    """ Holds datastore export metadata. """

    @classmethod
    def get_es_url_with_port(cls):
        result = None
        es_url = ApplicationConfigurationSecrets.get_es_url()
        if es_url:
            result = es_url + ":443"
        return result

    # e.g., name will be C4DatastoreTrialAlphaExportFoursightEnvBucket
    #       or might not contain '...Alpha...'
    # Also, name change in progress from EnvsBucket turning to EnvBucket, so match both
    _ENV_BUCKET_EXPORT_PATTERN = re.compile(".*Datastore.*Env.*Bucket")

    @classmethod
    def get_env_bucket(cls):
        return ConfigManager.find_stack_output(cls._ENV_BUCKET_EXPORT_PATTERN.match, value_only=True)

    _TIBANNA_OUTPUT_BUCKET_PATTERN = \
        re.compile(f".*Datastore.*{C4DatastoreExportsMixin.APPLICATION_TIBANNA_OUTPUT_BUCKET}")

    @classmethod
    def get_tibanna_output_bucket(cls):
        return ConfigManager.find_stack_output(cls._TIBANNA_OUTPUT_BUCKET_PATTERN.match, value_only=True)

    _FOURSIGHT_RESULT_BUCKET_PATTERN = re.compile(f".*Datastore.*FoursightResult")

    @classmethod
    def get_foursight_result_bucket(cls):
        return ConfigManager.find_stack_output(cls._FOURSIGHT_RESULT_BUCKET_PATTERN.match, value_only=True)

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce amount
        # of manual configuration
        parameter = 'DatastoreStackNameParameter'
        super().__init__(parameter)


class C4Datastore(C4DatastoreBase, C4Part):
    """ Defines the datastore stack - see resources created in build_template method. """

    # dmichaels/2022-06-09: Refactored these into C4DatastoreBase in constants.py.
    # STACK_NAME_TOKEN = "datastore"
    # STACK_TITLE_TOKEN = "Datastore"
    # APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX = "ApplicationConfiguration"

    SHARING = 'env'
    OPENSEARCH_LATEST = 'OpenSearch_2.3'

    @classmethod
    def rds_postgres_version(cls):
        return ConfigManager.get_config_setting(Settings.RDS_POSTGRES_VERSION, default=cls.DEFAULT_RDS_POSTGRES_VERSION)

    @classmethod
    def rds_postgres_major_version(cls):
        return cls.rds_postgres_version().split('.')[0]
    # dmichaels/2022-06-21: Factored out to C4DatastoreBase in constants.py
    # RDS_SECRET_NAME_SUFFIX = 'RDSSecret'  # Used as logical id suffix in resource names
    EXPORTS = C4DatastoreExports()
    NETWORK_EXPORTS = C4NetworkExports()
    IAM_EXPORTS = C4IAMExports()

    DEFAULT_ES_DATA_NODE_COUNT = '1'
    DEFAULT_ES_DATA_NODE_TYPE = 'c6g.large.elasticsearch'

    # Buckets used by the Application layer we need to initialize as part of the datastore
    # Intended to be .formatted with the deploying env_name

    APPLICATION_LAYER_BUCKETS = {
        C4DatastoreExports.APPLICATION_BLOBS_BUCKET: ConfigManager.AppBucketTemplate.BLOBS,
        C4DatastoreExports.APPLICATION_FILES_BUCKET: ConfigManager.AppBucketTemplate.FILES,
        C4DatastoreExports.APPLICATION_WFOUT_BUCKET: ConfigManager.AppBucketTemplate.WFOUT,
        C4DatastoreExports.APPLICATION_SYSTEM_BUCKET: ConfigManager.AppBucketTemplate.SYSTEM,
        C4DatastoreExports.APPLICATION_METADATA_BUNDLES_BUCKET: ConfigManager.AppBucketTemplate.METADATA_BUNDLES,
        C4DatastoreExports.APPLICATION_TIBANNA_OUTPUT_BUCKET: ConfigManager.AppBucketTemplate.TIBANNA_OUTPUT,
        C4DatastoreExports.APPLICATION_TIBANNA_CWL_BUCKET: ConfigManager.AppBucketTemplate.TIBANNA_CWL
    }

    # Buckets to apply the lifecycle policy to (files and wfoutput, as these are large)
    LIFECYCLE_BUCKET_EXPORT_NAMES = [
        C4DatastoreExports.APPLICATION_FILES_BUCKET,
        C4DatastoreExports.APPLICATION_WFOUT_BUCKET,
    ]

    @classmethod
    def application_layer_bucket(cls, export_name):
        bucket_name_template = cls.APPLICATION_LAYER_BUCKETS[export_name]
        bucket_name = cls.resolve_bucket_name(bucket_name_template)
        return bucket_name

    # Buckets used by the foursight layer
    # Envs describing the global foursight configuration in this account (could be updated)
    # Results bucket is the backing store for checks (they are also indexed into ES)

    # FOURSIGHT_LAYER_PREFIX = '{foursight_prefix}{env_name}'
    # TODO: Configure dev/prod stage result bucket correctly
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

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))
        # Adds IAM Stack Parameter
        template.add_parameter(Parameter(
            self.IAM_EXPORTS.reference_param_key,
            Description='Name of IAM stack for IAM role/instance profile references',
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

        # Add s3_encrypt_key, application configuration template
        # IMPORTANT: This s3_encrypt_key is different than the key used for admin access keys in the
        # system bucket. This key is used to encrypt all objects uploaded to s3.
        s3_encrypt_key = None
        encryption_enabled = ConfigManager.get_config_setting(Settings.S3_BUCKET_ENCRYPTION, default=False)
        if encryption_enabled:
            s3_encrypt_key = self.s3_encrypt_key()
            template.add_resource(s3_encrypt_key)
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
            use_lifecycle_policy = False
            if export_name in self.LIFECYCLE_BUCKET_EXPORT_NAMES:
                use_lifecycle_policy = True
            bucket_name = self.resolve_bucket_name(bucket_template)
            # use infra s3_encrypt_key for standard files if specified
            if encryption_enabled and export_name != C4DatastoreExports.APPLICATION_SYSTEM_BUCKET:
                bucket = self.build_s3_bucket(bucket_name, include_lifecycle=use_lifecycle_policy,
                                              s3_encrypt_key_ref=Ref(s3_encrypt_key))
                template.add_resource(bucket)  # must be added before policy
                template.add_resource(self.force_encryption_bucket_policy(bucket_name, bucket))
            else:  # do not set the policy if encryption is not enabled OR we are the system bucket
                bucket = self.build_s3_bucket(bucket_name, include_lifecycle=use_lifecycle_policy)
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

    @staticmethod
    def build_s3_lifecycle_policy() -> LifecycleConfiguration:
        """ Builds a standard life cycle policy for an S3 bucket based on the wfoutput bucket
            on CGAP production (using tags through foursight, to be implemented).
            Note that that these lifecycle policies are timelocked such that they cannot occur before
            the minimum number of days has passed.

            Tag an S3 object with:
                Lifecycle:IA to move the object to infrequent access
                Lifecycle:glacier to move the object to glacier
                Lifecycle:glacier_da to move the object to deep archive
                Lifecycle:expire to delete the current version after 24 hours
        """
        return LifecycleConfiguration(
            title='CGAPS3LifecyclePolicy',
            Rules=[
                LifecycleRule(
                    'IA',
                    Status='Enabled',
                    TagFilters=[TagFilter(Key='Lifecycle', Value='IA')],
                    Transition=LifecycleRuleTransition(
                        StorageClass='STANDARD_IA',
                        TransitionInDays=30
                    ),
                    NoncurrentVersionTransition=NoncurrentVersionTransition(
                        StorageClass='STANDARD_IA',
                        TransitionInDays=30
                    )
                ),
                LifecycleRule(
                    'glacier',
                    Status='Enabled',
                    TagFilters=[TagFilter(Key='Lifecycle', Value='Glacier')],
                    Transition=LifecycleRuleTransition(
                        StorageClass='GLACIER',
                        TransitionInDays=1
                    ),
                    NoncurrentVersionTransition=NoncurrentVersionTransition(
                        StorageClass='GLACIER',
                        TransitionInDays=1
                    )
                ),
                LifecycleRule(
                    'glacierda',
                    Status='Enabled',
                    TagFilters=[TagFilter(Key='Lifecycle', Value='GlacierDA')],
                    Transition=LifecycleRuleTransition(
                        StorageClass='DEEP_ARCHIVE',
                        TransitionInDays=1
                    ),
                    NoncurrentVersionTransition=NoncurrentVersionTransition(
                        StorageClass='DEEP_ARCHIVE',
                        TransitionInDays=1
                    )
                ),
                LifecycleRule(
                    'expire',
                    Status='Enabled',
                    TagFilters=[TagFilter(Key='Lifecycle', Value='expire')],
                    ExpirationInDays=1,
                    NoncurrentVersionExpiration=NoncurrentVersionExpiration(
                        NoncurrentDays=1
                    )
                )
            ]
        )

    @staticmethod
    def build_s3_bucket_encryption(s3_key_id) -> BucketEncryption:
        """ Builds a bucket encryption option for our s3 buckets using the created KMS key """
        return BucketEncryption(
            ServerSideEncryptionConfiguration=[
                ServerSideEncryptionRule(
                    ServerSideEncryptionByDefault=ServerSideEncryptionByDefault(
                        KMSMasterKeyID=s3_key_id,
                        SSEAlgorithm="aws:kms",
                    )
                )
            ]
        )

    def force_encryption_bucket_policy(self, bucket_name, bucket):
        """ Builds a bucket policy that makes the given bucket require encryption. """
        return BucketPolicy(
            f'{camelize(bucket_name)}EncryptionPolicy',
            DependsOn=[f'C4Bucket{camelize(bucket_name)}'],
            Bucket=bucket_name,
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Sid': 'DenyIncorrectEncryptionHeader',
                        'Effect': 'Deny',
                        'Principal': '*',
                        'Action': 's3:PutObject',
                        'Resource': f'arn:aws:s3:::{bucket_name}/*',
                        'Condition': {
                            'StringNotEquals': {
                                's3:x-amz-server-side-encryption': 'aws:kms'
                            }
                        }
                    },
                    {
                        'Sid': 'DenyUnEncryptedObjectUploads',
                        'Effect': 'Deny',
                        'Principal': '*',
                        'Action': 's3:PutObject',
                        'Resource': f'arn:aws:s3:::{bucket_name}/*',
                        'Condition': {
                            'Null': {
                                's3:x-amz-server-side-encryption': 'true'
                            }
                        }
                    }
                ]
            }
        )

    @classmethod
    def build_s3_bucket(cls, bucket_name, access_control=Private, include_lifecycle=True,
                        s3_encrypt_key_ref=None, versioning=True) -> Bucket:
        """ Creates an S3 bucket under the given name/access control permissions.
            See troposphere.s3 for access control options.

            Pass a ref to the created KMS key in order to enable KMS encryption on this bucket.
            Note that this change may require changes to our upload/download URLs.
        """
        # bucket_name_parts = bucket_name.split('-')
        bucket_kwargs = {
            "BucketName": bucket_name,
            "AccessControl": access_control,
            "LifecycleConfiguration": cls.build_s3_lifecycle_policy() if include_lifecycle else None,
            "BucketEncryption":
                cls.build_s3_bucket_encryption(s3_encrypt_key_ref) if s3_encrypt_key_ref is not None else None,
            "VersioningConfiguration": VersioningConfiguration(Status='Enabled') if versioning else None,
        }
        return Bucket(
            cls.build_s3_bucket_resource_name(bucket_name),
            **{k: v for k, v in bucket_kwargs.items() if v is not None}  # do not pass kwargs that are None
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

    def rds_secret_logical_id(self):
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        # dmichaels/2022-06-21: Refactored to use Names.rds_secret_logical_id() in names.py.
        # return self.name.logical_id(camelize(env_name) + self.RDS_SECRET_NAME_SUFFIX, context='rds_secret_logical_id')
        return Names.rds_secret_logical_id(env_name, self.name)

    def rds_secret(self) -> Secret:
        """ Returns the RDS secret, as generated and stored by AWS Secrets Manager """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.rds_secret_logical_id()
        return Secret(
            logical_id,
            Name=logical_id,
            Description=f'The RDS instance master password for {env_name}.',
            GenerateSecretString=GenerateSecretString(
                # TODO: Fix injection risk
                SecretStringTemplate='{"username":"%s"}' % ApplicationConfigurationSecrets.rds_db_username(),
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

            KeyPolicy creates two policies - one for admins who can manage the key, and
            one for the S3IAMUser (and Tibanna) for using the key for normal operation.
            Note that the roles are action restricted but not resource restricted.
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(camelize(env_name) + 'S3EncryptKey')
        return Key(
            logical_id,
            Description=f'Key for encrypting sensitive S3 files for {env_name} environment',
            KeyPolicy={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Sid': 'Enable Admin IAM Policies',
                        'Effect': 'Allow',
                        'Principal': {
                            'AWS': [
                                ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER)
                            ]
                        },
                        'Action': 'kms:*',  # Admins get full access
                        'Resource': '*'
                    },
                    {
                        'Sid': 'Allow use of the key',  # NOTE: this identifier must stay the same for tibanna
                        'Effect': 'Allow',
                        'Principal': {'AWS': [
                            Join('', ['arn:aws:iam::', AccountId, ':user/',
                                      self.IAM_EXPORTS.import_value(C4IAMExports.S3_IAM_USER)]),
                            # dmichaels/2022-06-17:
                            # Added to ECS_ASSUMED_IAM_ROLE to allow access to S3 with encrypted account.
                            Join('', ['arn:aws:iam::', AccountId, ':user/',
                                      self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)])
                        ]},
                        'Action': [
                            'kms:Encrypt',
                            'kms:Decrypt',
                            'kms:ReEncrypt*',
                            'kms:GenerateDataKey*',
                            'kms:DescribeKey'
                        ],
                        'Resource': '*'
                    }
                ]
            },
            KeySpec='SYMMETRIC_DEFAULT',  # (AES-256-GCM)
            Tags=self.tags.cost_tag_array()
        )

    def application_configuration_secret(self) -> Secret:
        """ Returns the application configuration secret. Note that this pushes up just a
            template - you must fill it out according to the specification in the README.
        """
        identity = ConfigManager.get_config_setting(Settings.IDENTITY)  # will use setting from config
        if not identity:
            # dmichaels/2022-06-06: Refactored to use Names.application_configuration_secret() in names.py.
            # identity = self.name.logical_id(camelize(
            #                ConfigManager.get_config_setting(Settings.ENV_NAME)) +
            #                    self.APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX)
            identity = Names.application_configuration_secret(
                ConfigManager.get_config_setting(Settings.ENV_NAME), self.name)
        return Secret(
            identity,
            Name=identity,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(ApplicationConfigurationSecrets.build_initial_values(), indent=2),
            Tags=self.tags.cost_tag_array()
        )

    def rds_subnet_group(self) -> DBSubnetGroup:
        """ Returns a subnet group for the single RDS instance in the infrastructure stack """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(camelize(env_name) + 'DBSubnetGroup')
        return DBSubnetGroup(
            logical_id,
            DBSubnetGroupDescription=f'RDS subnet group for {env_name}.',
            SubnetIds=[
                self.NETWORK_EXPORTS.import_value(subnet_key)
                for subnet_key in C4NetworkExports.PRIVATE_SUBNETS
            ],
            Tags=self.tags.cost_tag_array(),
        )

    @classmethod
    def rds_instance_name(cls, env_name):
        camelized = camelize(env_name)
        return f"{camelized}RDS"  # was RDSfor+...

    def rds_instance(self, instance_size=None,
                     az=None, storage_size=None, storage_type=None,
                     db_name=None, postgres_version=None) -> DBInstance:
        """ Returns the single RDS instance for the infrastructure stack. """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(self.rds_instance_name(env_name))  # was env_name
        secret_string_logical_id = self.rds_secret_logical_id()
        return DBInstance(
            logical_id,
            AllocatedStorage=storage_size or ConfigManager.get_config_setting(Settings.RDS_STORAGE_SIZE,
                                                                              default=self.DEFAULT_RDS_STORAGE_SIZE),
            DBInstanceClass=instance_size or ConfigManager.get_config_setting(Settings.RDS_INSTANCE_SIZE,
                                                                              default=self.DEFAULT_RDS_INSTANCE_SIZE),
            Engine='postgres',
            EngineVersion=postgres_version or self.DEFAULT_RDS_POSTGRES_VERSION,
            # was logical_id,
            DBInstanceIdentifier=ConfigManager.get_config_setting(Settings.RDS_NAME, default=None) or f"rds-{env_name}",
            DBName=db_name or ConfigManager.get_config_setting(Settings.RDS_DB_NAME, default=self.DEFAULT_RDS_DB_NAME),
            DBParameterGroupName=Ref(self.rds_parameter_group()),
            DBSubnetGroupName=Ref(self.rds_subnet_group()),
            StorageEncrypted=True,  # TODO use KmsKeyId to configure KMS key (requires db replacement)
            CopyTagsToSnapshot=True,
            AvailabilityZone=az or ConfigManager.get_config_setting(Settings.RDS_AZ, default=self.DEFAULT_RDS_AZ),
            PubliclyAccessible=False,
            StorageType=storage_type or ConfigManager.get_config_setting(Settings.RDS_STORAGE_TYPE,
                                                                         default=self.DEFAULT_RDS_STORAGE_TYPE),
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

    # def rds_password(self, resource: DBInstance) -> str:
    #     import pdb; pdb.set_trace()
    #     return GetAtt(resource, 'Endpoint.Password')

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
            Family='postgres{version}'.format(version=self.rds_postgres_major_version()),
            Parameters=parameters,
        )

    def rds_secret_attachment(self) -> SecretTargetAttachment:
        """ Attaches the rds_secret to the rds_instance. """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(camelize(env_name) + 'SecretRDSInstanceAttachment')
        return SecretTargetAttachment(
            logical_id,
            TargetType='AWS::RDS::DBInstance',
            SecretId=Ref(self.rds_secret()),
            TargetId=Ref(self.rds_instance()),
        )

    # def elasticsearch_instance(self, data_node_count=None, data_node_type=None) -> Domain:
    #     """ Returns an ElasticSearch domain with 1 data node, configurable via data_node_instance_type. Ref:
    #         https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticsearch-domain.html
    #         TODO allow master node configuration, update to opensearch
    #     """
    #     env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
    #     logical_id = self.name.logical_id(f"{camelize(env_name)}ElasticSearch")  # was env_name
    #     domain_name = self.name.domain_name(f"os-{env_name}")
    #     options = {}
    #     try:  # feature not yet supported by troposphere
    #         options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
    #     except NotImplementedError:
    #         pass
    #     # account_num = ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)
    #     domain = Domain(
    #         logical_id,
    #         DomainName=domain_name,
    #         NodeToNodeEncryptionOptions=NodeToNodeEncryptionOptions(Enabled=True),
    #         EncryptionAtRestOptions=EncryptionAtRestOptions(Enabled=True),  # TODO specify KMS key
    #         ElasticsearchClusterConfig=ElasticsearchClusterConfig(
    #             InstanceCount=(data_node_count
    #                            or ConfigManager.get_config_setting(Settings.ES_DATA_COUNT,
    #                                                                default=self.DEFAULT_ES_DATA_NODE_COUNT)),
    #             InstanceType=(data_node_type
    #                           or ConfigManager.get_config_setting(Settings.ES_DATA_TYPE,
    #                                                               default=self.DEFAULT_ES_DATA_NODE_TYPE)),
    #         ),
    #         ElasticsearchVersion='6.8',
    #         EBSOptions=EBSOptions(
    #             EBSEnabled=True,
    #             VolumeSize=ConfigManager.get_config_setting(Settings.ES_VOLUME_SIZE, 10),
    #             VolumeType='gp2',  # gp3?
    #         ),
    #         VPCOptions=VPCOptions(
    #             SecurityGroupIds=[
    #                 self.NETWORK_EXPORTS.import_value(C4NetworkExports.HTTPS_SECURITY_GROUP),
    #             ],
    #             SubnetIds=[
    #                 # TODO: Is this right? Just one subnet? -kmp 14-Aug-2021
    #                 # self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
    #                 self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNETS[0]),
    #             ],
    #         ),
    #         Tags=self.tags.cost_tag_array(name=domain_name),
    #         **options,
    #     )
    #     return domain

    def opensearch_instance(self, data_node_count=None, data_node_type=None) -> OSDomain:
        """ Returns an OpenSearch domain with 1 data node, configurable via data_node_instance_type. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticsearch-domain.html
            TODO allow master node configuration, update to opensearch
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(f"{camelize(env_name)}ElasticSearch")  # was env_name
        domain_name = self.name.domain_name(f"os-{env_name}")
        options = {}
        try:  # feature not yet supported by troposphere
            options['DomainEndpointOptions'] = DomainEndpointOptions(EnforceHTTPS=True)
        except NotImplementedError:
            pass
        # account_num = ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)
        domain = OSDomain(
            logical_id,
            DomainName=domain_name,
            NodeToNodeEncryptionOptions=NodeToNodeEncryptionOptions(Enabled=True),
            EncryptionAtRestOptions=EncryptionAtRestOptions(Enabled=True),  # TODO specify KMS key
            ClusterConfig=ClusterConfig(
                InstanceCount=(data_node_count
                               or ConfigManager.get_config_setting(Settings.ES_DATA_COUNT,
                                                                   default=self.DEFAULT_ES_DATA_NODE_COUNT)),
                InstanceType=(data_node_type
                              or ConfigManager.get_config_setting(Settings.ES_DATA_TYPE,
                                                                  default=self.DEFAULT_ES_DATA_NODE_TYPE)),
            ),
            EngineVersion=self.OPENSEARCH_LATEST,
            EBSOptions=EBSOptions(
                EBSEnabled=True,
                VolumeSize=ConfigManager.get_config_setting(Settings.ES_VOLUME_SIZE, 30),
                VolumeType='gp3',
            ),
            VPCOptions=VPCOptions(
                SecurityGroupIds=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.HTTPS_SECURITY_GROUP),
                ],
                SubnetIds=[
                    # TODO: Is this right? Just one subnet? -kmp 14-Aug-2021
                    # self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNETS[0]),
                ],
            ),
            Tags=self.tags.cost_tag_array(name=domain_name),
            **options,
        )
        return domain

    def output_es_url(self, resource: OSDomain, export_name=C4DatastoreExports.ES_URL) -> Output:
        """ Outputs ES URL """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='OS URL for this environment',
            Value=GetAtt(resource, 'DomainEndpoint'),
            Export=self.EXPORTS.export(export_name)
        )

    def build_sqs_instance(self, logical_id_suffix, name_suffix, timeout_in_minutes=10) -> Queue:
        """ Builds a SQS instance with the logical id suffix for CloudFormation and the given name_suffix for the queue
            name. Uses 'mastertest' as default cgap env. """
        logical_name = self.name.logical_id(logical_id_suffix)
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        queue_name = f'{env_name}-{name_suffix}'
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
