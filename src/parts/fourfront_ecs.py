from troposphere import (
    Parameter, Join, Ref, elasticloadbalancingv2 as elbv2,
    AWS_REGION, Template, Output, GetAtt,
)
from troposphere.ecs import (
    Cluster, TaskDefinition, ContainerDefinition, LogConfiguration,
    PortMapping, Service, LoadBalancer, AwsvpcConfiguration, NetworkConfiguration,
    Environment, CapacityProviderStrategyItem, SCHEDULING_STRATEGY_REPLICA,  # use for Fargate
)
from troposphere.ec2 import (
    SecurityGroup, SecurityGroupRule,
    SecurityGroupIngress, SecurityGroupEgress
)
from dcicutils.cloudformation_utils import camelize
from ..base import ConfigManager
from ..constants import Settings
from .ecs import C4ECSApplicationExports, C4ECSApplication
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
    VPC_SQS_URL = 'https://sqs.us-east-1.amazonaws.com/'

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
        template.add_parameter(self.ecs_subnet_a())
        template.add_parameter(self.ecs_subnet_b())

        # cluster
        template.add_resource(self.ecs_cluster())

        # ECS Tasks/Services
        template.add_resource(self.ecs_portal_task())
        portal = self.ecs_portal_service()
        template.add_resource(portal)
        template.add_resource(self.ecs_indexer_task())
        indexer = self.ecs_indexer_service()
        template.add_resource(indexer)
        template.add_resource(self.ecs_deployment_task(initial=True))
        template.add_resource(self.ecs_deployment_task())

        # Add Security Groups
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        # for rule in self.ecs_application_security_rules():
        #     template.add_resource(rule)

        # Add Target Group
        target_group = self.ecs_lbv2_target_group()
        template.add_resource(target_group)

        # Add load balancer for portal
        template.add_resource(self.ecs_application_load_balancer_listener(target_group))
        template.add_resource(self.ecs_application_load_balancer())

        # Add outputs
        template.add_output(self.output_application_url())
        return template

    @staticmethod
    def ecs_vpc() -> Parameter:
        """
        Parameter for the vpc we would like to deploy to
        """
        return Parameter(
            'ECSTargetVPC',
            Description='VPC to run containers in',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_VPC, default='vpc-5038bb34')
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
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_VPC_CIDR, default='172.31.0.0/16')
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
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_PRIMARY_SUBNET, default='subnet-0cc7a269')
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
            Default=ConfigManager.get_config_setting(Settings.FOURFRONT_SECONDARY_SUBNET, default='subnet-efb1b3c4')
        )

    def output_application_url(self, env=None) -> Output:
        """ Outputs URL to access portal. """
        env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Output(
            C4ECSApplicationExports.output_application_url_key(env),
            Description='URL of Fourfront-Portal.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def ecs_cluster(self) -> Cluster:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Cluster(
            # Always use env name for cluster
            camelize(env_name),
            CapacityProviders=['FARGATE', 'FARGATE_SPOT'],
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_application_security_group(self) -> SecurityGroup:
        """ Security group for the application. """
        logical_id = self.name.logical_id('ApplicationSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupDescription='Application Security Group.',
            VpcId=Ref(self.ecs_vpc()),
            Tags=self.tags.cost_tag_array()
        )

    def ecs_application_security_rules(self) -> [SecurityGroupRule]:
        """ Returns a list of inbound/outbound rules needed for
            the application to communicate.
            TODO: refactor to combine with version from network.py
        """
        return [
            SecurityGroupIngress(
                self.name.logical_id('ApplicationHTTPSInboundAccess', context='application_security_rules1'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundAllAccess', context='application_security_rules2'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationWebInboundAccess', context='application_security_rules3'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationWebOutboundAllAccess', context='application_security_rules4'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 80',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationNTPInboundAllAccess', context='application_security_rules5'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on udp port 123',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationNTPOutboundAllAccess', context='application_security_rules6'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on udp port 123',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess', context='application_security_rules7'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess', context='application_security_rules8'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 22',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationDBInboundAccess'),
                CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
                Description='allows database access on tcp ports 54xx',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=5400,
                ToPort=5499,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationDBOutboundAccess'),
                CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
                Description='allows outbound traffic to tcp 54xx',
                GroupId=Ref(self.ecs_application_security_group()),
                IpProtocol='tcp',
                FromPort=5400,
                ToPort=5499,
            )
        ]

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ Security group for the load balancer, allowing traffic on ports 80/443.
        """
        logical_id = self.name.logical_id('LBSecurityGroup')
        return SecurityGroup(
            logical_id,
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

    def ecs_container_security_group(self) -> SecurityGroup:
        """ Security group for the container runtime. """
        logical_id = self.name.logical_id('ContainerSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupDescription='Container Security Group',
            VpcId=Ref(self.ecs_vpc()),
            SecurityGroupIngress=[
                # HTTP from VPC CIDR
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp=Ref(self.ecs_vpc_cidr()),
                )
            ],
            Tags=self.tags.cost_tag_array()
        )

    def ecs_application_load_balancer(self) -> elbv2.LoadBalancer:
        """ Application load balancer for the portal ECS Task. """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id('LoadBalancer')
        return elbv2.LoadBalancer(
            logical_id,
            IpAddressType='ipv4',
            Name=env_name,  # was logical_id
            Scheme='internet-facing',
            SecurityGroups=[
                Ref(self.ecs_lb_security_group())
            ],
            Subnets=[Ref(self.ecs_subnet_a()), Ref(self.ecs_subnet_b())],
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type='application',
        )

    def ecs_lbv2_target_group(self) -> elbv2.TargetGroup:
        """ Creates LBv2 target group (intended for use with portal Service).
            Uses the VPC passed as parameter.
        """
        logical_id = self.name.logical_id('TargetGroup')
        return elbv2.TargetGroup(
            logical_id,
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
                        Environment(
                            Name='SQS_URL',
                            Value=self.VPC_SQS_URL
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
            DependsOn=[self.name.logical_id('LBListener')],
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
                        Ref(self.ecs_subnet_a()), Ref(self.ecs_subnet_b())  # deploy to subnet passed as argument
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
                        Environment(
                            Name='SQS_URL',
                            Value=self.VPC_SQS_URL
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
                        Ref(self.ecs_subnet_a()), Ref(self.ecs_subnet_b())
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_deployment_task(self, cpu=None, memory=None, identity=None, initial=False) -> TaskDefinition:
        """ Defines the Deployment task (run deployment action).
            Meant to be run manually from ECS Console (or from foursight), so no associated service.

            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task, default 256 (play with this value)
            :param memory: Memory amount for this task, default to 512 (play with this value)
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
            :param initial: boolean saying whether this task is intended to do the first deploy.
                            If it is, the environment variable INITIAL_DEPLOYMENT gets set to True,
                            causing a different initialization sequence.
        """
        return TaskDefinition(
            'FourfrontInitialDeployment' if initial else 'FourfrontDeployment',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpu or ConfigManager.get_config_setting(Settings.ECS_INITIAL_DEPLOYMENT_CPU
                                                        if initial else
                                                        Settings.ECS_DEPLOYMENT_CPU,
                                                        self.DEFAULT_INITIAL_DEPLOYMENT_CPU
                                                        if initial else
                                                        self.DEFAULT_DEPLOYMENT_CPU),
            Memory=memory or ConfigManager.get_config_setting(Settings.ECS_INITIAL_DEPLOYMENT_MEMORY
                                                              if initial else
                                                              Settings.ECS_DEPLOYMENT_MEMORY,
                                                              self.DEFAULT_INITIAL_DEPLOYMENT_MEMORY
                                                              if initial else
                                                              self.DEFAULT_DEPLOYMENT_MEMORY),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='DeploymentAction',
                    Essential=True,
                    Image=Join("", [
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
                            'awslogs-stream-prefix': 'fourfront-initial-deployment' if initial else 'cgap-deployment',
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=(identity or
                                   ConfigManager.get_config_setting(Settings.IDENTITY, self.LEGACY_DEFAULT_IDENTITY)),
                        ),
                        Environment(
                            Name='INITIAL_DEPLOYMENT',
                            Value="TRUE" if initial else "",
                        ),
                        Environment(
                            Name='application_type',
                            Value=FourfrontApplicationTypes.DEPLOYMENT
                        ),
                        Environment(
                            Name='SQS_URL',
                            Value=self.VPC_SQS_URL
                        ),
                    ]
                )
            ],
            Tags=self.tags.cost_tag_obj()
        )
