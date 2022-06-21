from troposphere import (
    Template, Parameter, Ref, Join
)
from troposphere.rds import DBInstance, DBSubnetGroup
from troposphere.elasticsearch import (
    Domain, ElasticsearchClusterConfig, DomainEndpointOptions,
    EBSOptions, EncryptionAtRestOptions, NodeToNodeEncryptionOptions, VPCOptions
)
from dcicutils.cloudformation_utils import camelize, dehyphenate
from ..base import (
    ConfigManager, Settings, APP_DEPLOYMENT,
)
from ..constants import DeploymentParadigm
from .datastore import C4Datastore, C4DatastoreExports


class C4DatastoreSlim(C4Datastore):
    """ Slim datastore lacking S3 related resources. """

    def build_template(self, template: Template) -> Template:
        """ Builds the "slim" datastore by omitting S3 resources and only
            creating RDS and ES in the network locations passed.
        """
        # TODO use Network Stack Parameter
        # template.add_parameter(Parameter(
        #     self.NETWORK_EXPORTS.reference_param_key,
        #     Description='Name of network stack for network import value references',
        #     Type='String',
        # ))

        # Add params
        template.add_parameter(self.ecs_vpc())
        template.add_parameter(self.ecs_subnet_a())
        template.add_parameter(self.ecs_subnet_b())
        template.add_parameter(self.rds_security_group())
        template.add_parameter(self.https_security_group())

        # Adds RDS primitives
        for i in [self.rds_secret(), self.rds_parameter_group(),
                  self.rds_subnet_group(), self.rds_secret_attachment()]:
            template.add_resource(i)

        # RDS instance
        rds = self.rds_instance()
        template.add_resource(rds)
        template.add_output(self.output_rds_url(rds))
        template.add_output(self.output_rds_port(rds))

        # Elasticsearch
        if APP_DEPLOYMENT == DeploymentParadigm.BLUE_GREEN:
            for env, export in {
                f'-{DeploymentParadigm.BLUE}': C4DatastoreExports.BLUE_ES_URL,
                f'-{DeploymentParadigm.GREEN}': C4DatastoreExports.GREEN_ES_URL
            }.items():
                env_name = ConfigManager.get_config_setting(Settings.ENV_NAME) + env
                es = self.elasticsearch_instance(env_name=env_name)
                template.add_resource(es)
                template.add_output(self.output_es_url(es, export_name=export))
        else:
            es = self.elasticsearch_instance()
            template.add_resource(es)
            template.add_output(self.output_es_url(es, export_name=C4DatastoreExports.ES_URL))
        return template

    # TODO: refactor parameters so they don't need to be repeated here
    @staticmethod
    def ecs_vpc() -> Parameter:
        """
        Parameter for the vpc we would like to deploy to
        """
        return Parameter(
            'ECSTargetVPC',
            Description='VPC to run containers in',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_VPC)
        )

    @staticmethod
    def ecs_vpc_cidr() -> Parameter:
        """
        Parameter for the vpc CIDR block we would like to deploy to
        """
        return Parameter(
            'ECSTargetCIDR',
            Description='CIDR block for VPC',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_VPC_CIDR)
        )

    @staticmethod
    def ecs_subnet_a() -> Parameter:
        """
        Parameter for the subnet we would like to deploy to
        """
        return Parameter(
            'ECSTargetSubnetA',
            Description='Primary Subnet to run containers in',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_PRIMARY_SUBNET)
        )

    @staticmethod
    def ecs_subnet_b() -> Parameter:
        """
        Parameter for the subnet we would like to deploy to
        """
        return Parameter(
            'ECSTargetSubnetB',
            Description='Second Subnet to run containers in',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_SECONDARY_SUBNET)
        )

    @staticmethod
    def rds_security_group() -> Parameter:
        """
        Get this value from the IAM stack
        TODO: automate
        """
        return Parameter(
            'DBSecurityGroup',
            Description='RDS Security Group',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_RDS_SECURITY_GROUP)
        )

    @staticmethod
    def https_security_group() -> Parameter:
        """
        Get this value from the IAM stack
        TODO: automate
        """
        return Parameter(
            'HTTPSSecurityGroup',
            Description='HTTPS Security Group',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_HTTPS_SECURITY_GROUP)
        )

    def rds_subnet_group(self) -> DBSubnetGroup:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(camelize(env_name) + 'DBSubnetGroup')
        return DBSubnetGroup(
            logical_id,
            DBSubnetGroupDescription=f'RDS subnet group for {env_name}.',
            SubnetIds=[
                Ref(self.ecs_subnet_a()), Ref(self.ecs_subnet_b())
            ],
            Tags=self.tags.cost_tag_array(),
        )

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
            DBInstanceIdentifier=f'rds-{env_name}',  # was logical_id,
            DBName=db_name or ConfigManager.get_config_setting(Settings.RDS_DB_NAME, default=self.DEFAULT_RDS_DB_NAME),
            DBParameterGroupName=Ref(self.rds_parameter_group()),
            DBSubnetGroupName=Ref(self.rds_subnet_group()),
            StorageEncrypted=True,  # TODO use KmsKeyId to configure KMS key (requires db replacement)
            CopyTagsToSnapshot=True,
            AvailabilityZone=az or ConfigManager.get_config_setting(Settings.RDS_AZ, default=self.DEFAULT_RDS_AZ),
            PubliclyAccessible=False,
            StorageType=storage_type or ConfigManager.get_config_setting(Settings.RDS_STORAGE_TYPE,
                                                                         default=self.DEFAULT_RDS_STORAGE_TYPE),
            VPCSecurityGroups=[Ref(self.rds_security_group())],
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

    def elasticsearch_instance(self, env_name=None, data_node_count=None, data_node_type=None):
        """ Returns an Elasticsearch domain with 1 data node, configurable via data_node_instance_type. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticsearch-domain.html
            TODO allow master node configuration
        """
        if not env_name:
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = f'{dehyphenate(env_name)}ElasticSearch'
        domain_name = self.name.domain_name(f'es-{env_name}')
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
                InstanceCount=(data_node_count
                               or ConfigManager.get_config_setting(Settings.ES_DATA_COUNT,
                                                                   default=self.DEFAULT_ES_DATA_NODE_COUNT)),
                InstanceType=(data_node_type
                              or ConfigManager.get_config_setting(Settings.ES_DATA_TYPE,
                                                                  default=self.DEFAULT_ES_DATA_NODE_TYPE)),
            ),
            ElasticsearchVersion='6.8',
            EBSOptions=EBSOptions(
                EBSEnabled=True,
                VolumeSize=ConfigManager.get_config_setting(Settings.ES_VOLUME_SIZE, 10),
                VolumeType='gp2',  # gp3?
            ),
            VPCOptions=VPCOptions(
                SecurityGroupIds=[
                    Ref(self.https_security_group()),
                ],
                SubnetIds=[
                    Ref(self.ecs_subnet_a()),
                ],
            ),
            Tags=self.tags.cost_tag_array(name=domain_name),
            **options,
        )
        return domain
