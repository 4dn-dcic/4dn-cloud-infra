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
from dcicutils.cloudformation_utils import camelize, dehyphenate
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
    ECR_EXPORTS = C4ECRExports()
    IAM_EXPORTS = C4IAMExports()
    LOGGING_EXPORTS = C4LoggingExports()
    AMI = 'ami-0be13a99cd970f6a9'  # latest amazon linux 2 ECS optimized
    LB_NAME = 'AppLB'
    IMAGE_TAG = ConfigManager.get_config_setting(Settings.ECS_IMAGE_TAG, 'latest')
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

        # cluster
        template.add_resource(self.ecs_cluster())

        # ECS Tasks/Services
        template.add_resource(self.ecs_portal_task())
        portal = self.ecs_portal_service()
        template.add_resource(portal)

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

    def ecs_cluster(self) -> Cluster:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Cluster(
            # Fallback, but should always be set
            f'FourfrontDockerClusterFor{camelize(env_name)}',
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
        TODO: get this value
        """
        return Parameter(
            'ECSTargetCIDR',
            Description='CIDR block for VPC',
            Type='String',
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

    def ecs_portal_task(self, cpu='256', mem='512', identity=None) -> TaskDefinition:
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
