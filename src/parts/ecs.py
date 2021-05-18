import os
from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancingv2 as elbv2,
    AWS_REGION,
    Template,
    Output,
    GetAtt
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
from troposphere.applicationautoscaling import ScalableTarget, ScalingPolicy, PredefinedMetricSpecification, TargetTrackingScalingPolicyConfiguration
from src.constants import ENV_NAME
from src.part import C4Part
from src.parts.network import C4NetworkExports, C4Network
from src.parts.ecr import C4ECRExports
from src.parts.iam import C4IAMExports
from src.parts.logging import C4LoggingExports


class C4ECSApplication(C4Part):
    """ Configures the ECS Cluster Application for CGAP
        This class contains everything necessary for running CGAP on ECS, including:
            * Cluster
            * Application Load Balancer (Fargate compatible)
            * ECS Tasks/Services
                * WSGI
                * Indexer
                * Ingester
            * TODO: Autoscaling
    """
    NETWORK_EXPORTS = C4NetworkExports()
    ECR_EXPORTS = C4ECRExports()
    IAM_EXPORTS = C4IAMExports()
    LOGGING_EXPORTS = C4LoggingExports()
    AMI = 'ami-0be13a99cd970f6a9'  # latest amazon linux 2 ECS optimized
    LB_NAME = 'AppLB'

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

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

        # ECS Params
        template.add_parameter(self.ecs_web_worker_port())
        # template.add_parameter(self.ecs_lb_certificate())  # TODO must be provisioned
        template.add_parameter(self.ecs_web_worker_memory())
        template.add_parameter(self.ecs_web_worker_cpu())

        # ECS
        template.add_resource(self.ecs_cluster())

        # ECS Tasks/Services
        template.add_resource(self.ecs_wsgi_task())
        wsgi = self.ecs_wsgi_service()
        template.add_resource(wsgi)
        template.add_resource(self.ecs_indexer_task())
        indexer = template.add_resource(self.ecs_indexer_service())
        template.add_resource(self.ecs_ingester_task())
        ingester = template.add_resource(self.ecs_ingester_service())
        template.add_resource(self.ecs_deployment_task())
        template.add_resource(self.ecs_deployment_service())

        # Add load balancer for WSGI
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        target_group = self.ecs_lbv2_target_group()
        template.add_resource(target_group)
        template.add_resource(self.ecs_application_load_balancer_listener(target_group))
        template.add_resource(self.ecs_application_load_balancer())

        # TODO: Enable WSGI, Indexer, Ingester autoscaling
        # wsgi_scalable_target = self.ecs_wsgi_scalable_target(wsgi)
        # template.add_resource(wsgi_scalable_target)
        # template.add_resource(self.ecs_wsgi_scaling_policy(wsgi_scalable_target))
        # indexer_scalable_target = self.ecs_indexer_scalable_target(indexer)
        # template.add_resource(indexer_scalable_target)
        # use wsgi scaling policy for others as well (for now)
        # template.add_resource(self.ecs_wsgi_scaling_policy(indexer_scalable_target))
        # ingester_scalable_target = self.ecs_ingester_scalable_target(ingester)
        # template.add_resource(ingester_scalable_target)
        # template.add_resource(self.ecs_wsgi_scaling_policy(ingester_scalable_target))

        # Add outputs
        template.add_output(self.output_application_url())
        return template

    def ecs_cluster(self) -> Cluster:
        """ Creates an ECS cluster for use with this portal deployment. """
        return Cluster(
            os.environ.get(ENV_NAME, 'CGAPDockerCluster').replace('-', ''),  # Fallback, but should always be set
            CapacityProviders=['FARGATE', 'FARGATE_SPOT'],
            # Tags=self.tags.cost_tag_array() XXX: bug in troposphere - does not take tags array
        )

    @staticmethod
    def ecs_lb_certificate() -> Parameter:
        """ Allows us to eventually pass this as an argument and configure application LB to use it. """
        return Parameter(
            "CertId",
            Description='This is the SSL Cert to attach to the LB',
            Type='String'
        )

    @staticmethod
    def ecs_web_worker_port() -> Parameter:
        """ Parameter for the WSGI port - by default 8000 (requires change to nginx config on cgap-portal to modify) """
        return Parameter(
            'WebWorkerPort',
            Description='Web worker container exposed port',
            Type='Number',
            Default=8000,  # port exposed by WSGI container
        )

    def ecs_container_security_group(self) -> SecurityGroup:
        """ Security group for the container runtime. """
        return SecurityGroup(
            'ContainerSecurityGroup',
            GroupDescription='Container Security Group.',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            SecurityGroupIngress=[
                # HTTP from web public subnets
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
                # SSH access - not usable on Fargate (?) - Will 5/5/21
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=22,
                    ToPort=22,
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
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
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
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

    def ecs_application_load_balancer_listener(self, target_group: elbv2.TargetGroup) -> elbv2.Listener:
        """ Listener for the application load balancer, forwards traffic to the target group (containing WSGI). """
        return elbv2.Listener(
            'ECSLBListener',
            Port=80,
            Protocol='HTTP',
            LoadBalancerArn=Ref(self.ecs_application_load_balancer()),
            DefaultActions=[
                elbv2.Action(Type='forward', TargetGroupArn=Ref(target_group))
            ]
        )

    def ecs_application_load_balancer(self) -> elbv2.LoadBalancer:
        """ Application load balancer for the WSGI ECS Task. """
        env_identifier = os.environ.get(ENV_NAME).replace('-', '')
        if not env_identifier:
            raise Exception('Did not set required key in .env! Should never get here.')
        logical_id = self.name.logical_id(env_identifier)
        return elbv2.LoadBalancer(
            logical_id,
            IpAddressType='ipv4',
            Name=logical_id,
            Scheme='internet-facing',
            SecurityGroups=[
                Ref(self.ecs_lb_security_group())
            ],
            Subnets=[
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            ],
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type='application',
        )

    def output_application_url(self, env='cgap-mastertest') -> Output:
        """ Outputs URL to access WSGI. """
        return Output(
            'ECSApplicationURL%s' % env.replace('-', ''),
            Description='URL of CGAP-Portal.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def ecs_lbv2_target_group(self) -> elbv2.TargetGroup:
        """ Creates LBv2 target group (intended for use with WSGI Service). """
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
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array()
        )

    @staticmethod
    def ecs_web_worker_cpu() -> Parameter:
        """ TODO: figure out how to best use - should probably be per service? """
        return Parameter(
            'WebWorkerCPU',
            Description='Web worker CPU units',
            Type='Number',
            Default=256,
        )

    @staticmethod
    def ecs_web_worker_memory() -> Parameter:
        """ TODO: figure out how to best use - should probably be per service? """
        return Parameter(
            'WebWorkerMemory',
            Description='Web worker memory',
            Type='Number',
            Default=512,
        )

    def ecs_wsgi_task(self, cpus='256', mem='512', app_revision='latest',
                      identity='dev/beanstalk/cgap-dev') -> TaskDefinition:
        """ Defines the WSGI Task (serve HTTP requests).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            'CGAPWSGI',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='WSGI',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
                        ':',
                        app_revision,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(self.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-wsgi'
                        }
                    ),
                    Environment=[
                        # VERY IMPORTANT - this environment variable determines which identity in the secrets manager to use
                        # If this secret does not exist, things will not start up correctly - this is ok in the short term,
                        # but shortly after orchestration the secret value should be set.
                        # Note this applies to all other tasks as well.
                        Environment(
                            Name='IDENTITY',
                            Value=identity
                        )
                    ]
                )
            ],
            # Tags=self.tags.cost_tag_array(),  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_wsgi_service(self, concurrency=8) -> Service:
        """ Defines the WSGI service (manages WSGI Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer

            Defined by the ECR Image tag 'latest'.

            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 8, approximately matching our current resources.
        """
        return Service(
            "CGAPWSGIService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['ECSLBListener'],  # XXX: Hardcoded, important!
            DesiredCount=concurrency,
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='WSGI',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group()))
            ],
            LaunchType='FARGATE',
            # Run WSGI service on Fargate Spot
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
            TaskDefinition=Ref(self.ecs_wsgi_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_wsgi_scalable_target(self, wsgi: Service, max_concurrency=8) -> ScalableTarget:
        """ Scalable Target for the WSGI Service. """
        return ScalableTarget(
            'WSGIScalableTarget',
            RoleARN=self.IAM_EXPORTS.import_value(C4IAMExports.AUTOSCALING_IAM_ROLE),
            ResourceId=Ref(wsgi),
            ServiceNamespace='ecs',
            ScalableDimension='ecs:service:DesiredCount',
            MinCapacity=2,  # this should match 'concurrency'
            MaxCapacity=max_concurrency  # scale up to 8 WSGI workers if needed
        )

    def ecs_wsgi_scaling_policy(self, scalable_target: ScalableTarget):
        """ Determines the policy from which a scaling event should occur for WSGI.
            Right now, does something simple, like: scale up once average application server CPU reaches 80%
            Note that by increasing vCPU allocation we can reduce how often this occurs.
        """
        return ScalingPolicy(
            'WSGIScalingPolicy',
            PolicyType='TargetTrackingScaling',
            ScalingTargetId=Ref(scalable_target),
            TargetTrackingScalingPolicyConfiguration=TargetTrackingScalingPolicyConfiguration(
                PredefinedMetricSpecification(
                    'CPUUtilization',
                    PredefinedMetricType='ECSServiceAverageCPUUtilization'
                )
            ),
            TargetValue=80.0
        )

    def ecs_indexer_task(self, cpus='256', mem='512', app_revision='latest-indexer',
                         identity='dev/beanstalk/cgap-dev') -> TaskDefinition:
        """ Defines the Indexer task (indexer app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            'CGAPIndexer',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Essential=True,
                    Image=Join('', [
                        self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-indexer'
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=identity
                        )
                    ]
                )
            ],
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_indexer_service(self, concurrency=4) -> Service:
        """ Defines the Indexer service (manages Indexer Tasks)
            TODO SQS autoscaling trigger?

            Defined by the ECR Image tag 'latest-indexer'.

            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 4, approximately matching our current resources.
        """
        return Service(
            "CGAPIndexerService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=concurrency,
            LaunchType='FARGATE',
            # XXX: let's see how indexing does on Fargate Spot
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
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_indexer_scalable_target(self, indexer: Service, max_concurrency=16) -> ScalableTarget:
        """ Scalable Target for the Indexer Service. """
        return ScalableTarget(
            'IndexerScalableTarget',
            RoleARN=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ResourceId=Ref(indexer),
            ServiceNamespace='ecs',
            ScalableDimension='ecs:service:DesiredCount',
            MinCapacity=1,
            MaxCapacity=max_concurrency  # scale indexing to 16 workers if needed
        )

    def ecs_ingester_task(self, cpus='512', mem='1024', app_revision='latest-ingester',
                          identity='dev/beanstalk/cgap-dev') -> TaskDefinition:
        """ Defines the Ingester task (ingester app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            'CGAPIngester',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Ingester',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-ingester'
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=identity
                        )
                    ]
                )
            ],
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_ingester_service(self) -> Service:
        """ Defines the Ingester service (manages Ingestion Tasks)

            Defined by the ECR Image tag 'latest-ingester'
            TODO SQS Trigger?
        """
        return Service(
            "CGAPIngesterService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=1,
            LaunchType='FARGATE',
            TaskDefinition=Ref(self.ecs_ingester_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            # Run ingester service on normal Fargate as this could be even more long running than indexing
            CapacityProviderStrategy=[
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE',
                    Base=1,
                    Weight=1
                ),
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE_SPOT',
                    Base=0,
                    Weight=0
                )
            ],
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_ingester_scalable_target(self, ingester: Service, max_concurrency=4) -> ScalableTarget:
        """ Scalable Target for the Indexer Service. """
        return ScalableTarget(
            'IngesterScalableTarget',
            RoleARN=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ResourceId=Ref(ingester),
            ServiceNamespace='ecs',
            ScalableDimension='ecs:service:DesiredCount',
            MinCapacity=1,
            MaxCapacity=max_concurrency  # scale ingester to 4 workers if needed
        )

    # def ecs_ingester_scaling_policy(self, scalable_target: ScalableTarget):
    #     """ Determines the policy from which a scaling event should occur for the ingester.
    #         Right now, does something simple, like: scale up once average application server CPU reaches 80%
    #         Note that by increasing vCPU allocation we can reduce how often this occurs.
    #     """
    #     return ScalingPolicy(
    #         'WSGIScalingPolicy',
    #         PolicyType='TargetTrackingScaling',
    #         ScalingTargetId=Ref(scalable_target),
    #         TargetTrackingConfiguration=TargetTrackingConfiguration(
    #             PredefinedMetricSpecification(
    #                 'CPUUtilization',
    #                 PredefinedMetricType='ECSServiceAverageCPUUtilization'
    #             )
    #         ),
    #         TargetValue=80.0
    #     )

    def ecs_deployment_task(self, cpus='256', mem='512', app_revision='latest-deployment',
                            identity='dev/beanstalk/cgap-dev') -> TaskDefinition:
        """ Defines the Ingester task (ingester app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            'CGAPDeployment',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='DeploymentAction',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-deployment'
                        }
                    ),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=identity
                        )
                    ]
                )
            ],
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )

    def ecs_deployment_service(self) -> Service:
        """ Defines the Deployment service to trigger the actions we currently associate with deployment, namely:
                1. Runs clear-db-es-contents. Ensure env.name is configured appropriately!
                2. Runs create-mapping-on-deploy.
                3. Runs load-data.
                4. Runs load-access-keys.

            Defined by the ECR Image tag 'latest-deployment'.
            TODO foursight Trigger?
        """
        return Service(
            "CGAPDeploymentService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=0,  # Explicitly triggered
            LaunchType='FARGATE',
            # deployments should happen fast enough to tolerate potential interruption
            CapacityProviderStrategy=[
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE',
                    Base=0,
                    Weight=0
                ),
                CapacityProviderStrategyItem(
                    CapacityProvider='FARGATE_SPOT',
                    Base=1,
                    Weight=1
                )
            ],
            TaskDefinition=Ref(self.ecs_deployment_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            # Tags=self.tags.cost_tag_array()  # XXX: bug in troposphere - does not take tags array
        )
