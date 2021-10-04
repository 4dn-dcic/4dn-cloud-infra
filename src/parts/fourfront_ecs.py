import json
from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancingv2 as elbv2,
    AWS_REGION,
    Template,
    Output,
    GetAtt,
)
from troposphere.ecs import (
    Cluster,
    TaskDefinition,
    ContainerDefinition,
    LogConfiguration,
    PortMapping,
    Service,
    LoadBalancer,
    AwsvpcConfiguration,
    NetworkConfiguration,
    Environment,
    CapacityProviderStrategyItem,
    SCHEDULING_STRATEGY_REPLICA,  # use for Fargate
)
from troposphere.ec2 import SecurityGroup, SecurityGroupRule
from troposphere.secretsmanager import Secret
from dcicutils.cloudformation_utils import camelize, dehyphenate
from ..constants import Secrets
from ..base import ConfigManager
from ..constants import Settings
from .ecs import C4ECSApplicationExports, C4ECSApplication
from .datastore import C4Datastore
from .ecr import C4ECRExports
from .iam import C4IAMExports
from .logging import C4LoggingExports


class FourfrontApplicationTypes:
    """ Defines the set of possible fourfront applicaation types. """
    PORTAL = 'portal'
    INDEXER = 'indexer'
    DEPLOYMENT = 'deployment'


class FourfrontApplicationExports(C4ECSApplicationExports):
    """ Use same exports as standard (CGAP) ECS. """
    pass


class FourfrontECSApplication(C4ECSApplication):
    """ Configures an ECS Cluster application for Fourfront """
    LEGACY_DEFAULT_IDENTITY = 'fourfront-mastertest'

    def build_template(self, template: Template) -> Template:
        """ We override the build template method here so we can do things drastically
            different from the standard ECS setup.

            In this setup, we assume an existing global application configuration in
            the name expected by the IAM Stack.

            We hardwire the current EB environment configuration into the GAC so it can
            use existing resources/buckets.

            We pass the subnet we would like to deploy ECS tasks into.
        """
        # Adds ECR Stack Parameter
        template.add_parameter(Parameter(
            self.ECR_EXPORTS.reference_param_key,
            Description='Name of ECR stack for getting repo URL',
            Type='String',
        ))
        # Adds IAM Stack Parameter
        template.add_parameter(Parameter(
            self.IAM_EXPORTS.reference_param_key,
            Description='Name of IAM stack for IAM role/instance profile references',
            Type='String',
        ))
        # Adds logging Stack Parameter (just creates a log group for now)
        template.add_parameter(Parameter(
            self.LOGGING_EXPORTS.reference_param_key,
            Description='Name of Logging stack for referencing the log group',
            Type='String',
        ))

        # Standard params
        template.add_parameter(self.ecs_web_worker_port())
        template.add_parameter(self.ecs_vpc())
        template.add_parameter(self.ecs_vpc_cidr())
        template.add_parameter(self.ecs_subnet())

        # GAC
        template.add_resource(self.application_configuration_secret())

        # cluster
        template.add_resource(self.ecs_cluster())

        # ECS Tasks/Services
        template.add_resource(self.ecs_portal_task())
        portal = self.ecs_portal_service()
        template.add_resource(portal)
        template.add_resource(self.ecs_indexer_task())
        indexer = self.ecs_indexer_service()
        template.add_resource(indexer)

        # Add load balancer for portal
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        target_group = self.ecs_lbv2_target_group()
        template.add_resource(target_group)
        template.add_resource(self.ecs_application_load_balancer_listener(target_group))
        template.add_resource(self.ecs_application_load_balancer())

        # Add outputs
        template.add_output(self.output_application_url())
        return template

    @classmethod
    def add_placeholders(cls, template):
        """ TODO: move to dcicutils? """
        return {
            k: C4Datastore.CONFIGURATION_PLACEHOLDER if v is None else v
            for k, v in template.items()
        }

    @classmethod
    def application_configuration_template(cls):
        """ Template for GAC for fourfront - very similar but not
            exactly the same as for CGAP.
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        result = cls.add_placeholders({
            'deploying_iam_user': ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER),  # required
            'S3_AWS_ACCESS_KEY_ID': None,
            'S3_AWS_SECRET_ACCESS_KEY': None,
            'ENCODED_AUTH0_CLIENT': ConfigManager.get_config_secret(Secrets.AUTH0_CLIENT, default=None),
            'ENCODED_AUTH0_SECRET': ConfigManager.get_config_secret(Secrets.AUTH0_SECRET, default=None),
            'ENV_NAME': env_name,
            'ENCODED_APPLICATION_BUCKET_PREFIX': '',
            'ENCODED_BS_ENV': env_name,
            'ENCODED_DATA_SET': 'prod',
            'ENCODED_ES_SERVER': '',  # XXX: Pass as argument or fill in existing
            'ENCODED_FOURSIGHT_BUCKET_PREFIX': '',
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
            'RDS_DB_NAME': 'ebdb',
            'RDS_PORT': '5432',
            'RDS_USERNAME': 'postgres',
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

    def application_configuration_secret(self) -> Secret:
        """ Builds a GAC for fourfront - see datastore.py application_configuration_secret """
        identity = ConfigManager.get_config_setting(Settings.IDENTITY)
        return Secret(
            dehyphenate(identity),
            Name=identity,
            Description='This secret defines the application configuration for the orchestrated environment.',
            SecretString=json.dumps(C4Datastore.application_configuration_template(), indent=2),
            Tags=self.tags.cost_tag_array()
        )

    def ecs_cluster(self) -> Cluster:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Cluster(
            # Always use env name for cluster
            camelize(env_name),
            CapacityProviders=['FARGATE', 'FARGATE_SPOT'],
            Tags=self.tags.cost_tag_obj()
        )

    @staticmethod
    def ecs_vpc() -> Parameter:
        """
        Parameter for the vpc we would like to deploy to
        """
        return Parameter(
            'ECSTargetVPC',
            Description='VPC to run containers in',
            Type='String',
            Default='vpc-5038bb34'  # XXX: make config value? default vpc ID in main account
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
            Default='172.31.0.0/16'  # XXX: make config value? default VPC CIDR
        )

    @staticmethod
    def ecs_subnet() -> Parameter:
        """
        Parameter for the subnet we would like to deploy to
        """
        return Parameter(
            'ECSTargetSubnet',
            Description='Subnet to run containers in',
            Type='String',
            Default='subnet-0cc7a269'  # XXX: make config value? this value is us-east-1a in our default VPC
        )

    def output_application_url(self, env=None) -> Output:
        """ Outputs URL to access portal. """
        env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Output(
            C4ECSApplicationExports.output_application_url_key(env),
            Description='URL of Fourfront-Portal.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def ecs_container_security_group(self) -> SecurityGroup:
        """ Security group for the container runtime. """
        return SecurityGroup(
            'ContainerSecurityGroup',
            GroupDescription='Container Security Group.',
            VpcId=Ref(self.ecs_vpc()),
            SecurityGroupIngress=[
                # HTTP from web public subnets
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp=Ref(self.ecs_vpc_cidr()),
                )
            ],
            Tags=self.tags.cost_tag_array()
        )

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ Security group for the load balancer, allowing traffic on ports 80/443.
            TODO: configure for HTTPS.
        """
        return SecurityGroup(
            "ECSLBSSLSecurityGroup",
            GroupDescription="Web load balancer security group.",
            VpcId=Ref(self.ecs_vpc()),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=443,
                    ToPort=443,
                    CidrIp='0.0.0.0/0',
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=80,
                    ToPort=80,
                    CidrIp='0.0.0.0/0',
                ),
            ],
            Tags=self.tags.cost_tag_array()
        )

    def ecs_application_load_balancer(self) -> elbv2.LoadBalancer:
        """ Application load balancer for the portal ECS Task. """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        env_identifier = dehyphenate(env_name)
        logical_id = self.name.logical_id(env_identifier, context='ecs_application_load_balancer')
        return elbv2.LoadBalancer(
            logical_id,
            IpAddressType='ipv4',
            Name=env_name,  # was logical_id
            Scheme='internet-facing',
            SecurityGroups=[
                Ref(self.ecs_lb_security_group())
            ],
            Subnets=[Ref(self.ecs_subnet())],
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type='application',
        )

    def ecs_lbv2_target_group(self) -> elbv2.TargetGroup:
        """ Creates LBv2 target group (intended for use with portal Service).
            Uses the VPC passed as parameter.
        """
        return elbv2.TargetGroup(
            'TargetGroupApplication',
            HealthCheckIntervalSeconds=60,
            HealthCheckPath='/health?format=json',
            HealthCheckProtocol='HTTP',
            HealthCheckTimeoutSeconds=10,
            Matcher=elbv2.Matcher(HttpCode='200'),
            Name='TargetGroupApplication',
            Port=Ref(self.ecs_web_worker_port()),
            TargetType='ip',
            Protocol='HTTP',
            VpcId=Ref(self.ecs_vpc()),
            Tags=self.tags.cost_tag_array()
        )

    def ecs_portal_task(self, cpu='1024', mem='2048', identity=None) -> TaskDefinition:
        """ Defines the portal Task (serve HTTP requests).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html
            Note that not much has changed for the FF version.

            :param cpu: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            'FourfrontPortal',
            RequiresCompatibilities=['FARGATE'],
            Cpu=ConfigManager.get_config_setting(Settings.ECS_WSGI_CPU, cpu),
            Memory=ConfigManager.get_config_setting(Settings.ECS_WSGI_MEMORY, mem),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='portal',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(self.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group':
                                self.LOGGING_EXPORTS.import_value(C4LoggingExports.APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'fourfront-portal'
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=(identity
                                   or ConfigManager.get_config_setting(Settings.IDENTITY,
                                                                       self.LEGACY_DEFAULT_IDENTITY)),
                        ),
                        Environment(
                            Name='application_type',
                            Value=FourfrontApplicationTypes.PORTAL
                        ),
                    ]
                )
            ],
            Tags=self.tags.cost_tag_obj(),
        )

    def ecs_portal_service(self, concurrency=8) -> Service:
        """ Defines the portal service (manages portal Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer

            Defined by the ECR Image tag 'latest'.

            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 8, approximately matching our current resources.
        """  # noQA - ignore line length issues
        return Service(
            "FourfrontPortalService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['ECSLBListener'],  # XXX: Hardcoded, important!
            DesiredCount=ConfigManager.get_config_setting(Settings.ECS_WSGI_COUNT, concurrency),
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='portal',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group()))
            ],
            # Run portal service on Fargate Spot
            CapacityProviderStrategy=[
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE',
                    Base=0,
                    Weight=0
                ),
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE_SPOT',
                    Base=concurrency,
                    Weight=1
                )
            ],
            TaskDefinition=Ref(self.ecs_portal_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[
                        Ref(self.ecs_subnet())  # deploy to subnet passed as argument
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_indexer_task(self, cpu=None, memory=None, identity=None) -> TaskDefinition:
        """ Defines the Indexer task (indexer app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task, default 256 (play with this value)
            :param memory: Memory amount for this task, default to 512 (play with this value)
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
        """
        return TaskDefinition(
            'FourfrontIndexer',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpu or ConfigManager.get_config_setting(Settings.ECS_INDEXER_CPU, self.DEFAULT_INDEXER_CPU),
            Memory=memory or ConfigManager.get_config_setting(Settings.ECS_INDEXER_MEMORY, self.DEFAULT_INDEXER_MEMORY),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Essential=True,
                    Image=Join('', [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group':
                                self.LOGGING_EXPORTS.import_value(C4LoggingExports.APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'fourfront-indexer'
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=(identity or
                                   # TODO: We should be able to discover this value without
                                   #       it being in the config.json -kmp 13-Aug-2021
                                   ConfigManager.get_config_setting(Settings.IDENTITY, self.LEGACY_DEFAULT_IDENTITY)),
                        ),
                        Environment(
                            Name='application_type',
                            Value=FourfrontApplicationTypes.INDEXER
                        ),
                    ]
                )
            ],
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_indexer_service(self, concurrency=4) -> Service:
        """ Defines the Indexer service (manages Indexer Tasks)
            TODO SQS autoscaling trigger?

            Defined by the ECR Image tag 'latest-indexer'.

            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 4, approximately matching our current resources.
        """
        return Service(
            "FourfrontIndexerService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=ConfigManager.get_config_setting(Settings.ECS_INDEXER_COUNT, concurrency),
            CapacityProviderStrategy=[
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE',
                    Base=0,
                    Weight=0
                ),
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE_SPOT',
                    Base=concurrency,
                    Weight=1
                )
            ],
            TaskDefinition=Ref(self.ecs_indexer_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[
                        self.ecs_subnet()
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )
