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
    SCHEDULING_STRATEGY_REPLICA,  # use for Fargate
    SCHEDULING_STRATEGY_DAEMON  # use for EC2 ?
)
from troposphere.ec2 import (
    SecurityGroup,
    SecurityGroupRule,
)
from src.part import C4Part
from src.parts.network import C4NetworkExports, C4Network
from src.parts.ecr import C4ECRExports
from src.parts.iam import C4IAMExports
from src.parts.logging import C4LoggingExports


class C4ECSApplication(C4Part):
    """ Configures the ECS Cluster Application for CGAP
        This class contains everything necessary for running CGAP on ECS, including:
            * The Cluster itself (done)
            * The Load Balancer that forwards traffic to the Cluster
            * Container instance
            * Autoscaling Group
            * ECS Tasks
                * WSGI
                * Indexer
                * Ingester
            * ECS Services
                * WSGI
                * Indexer
                * Ingester

        Note: application upload handling is still TODO
    """
    NETWORK_EXPORTS = C4NetworkExports()
    ECR_EXPORTS = C4ECRExports()
    IAM_EXPORTS = C4IAMExports()
    LOGGING_EXPORTS = C4LoggingExports()
    AMI = 'ami-0be13a99cd970f6a9'  # latest amazon linux 2 ECS optimized
    LB_NAME = 'ECSApplicationLoadBalancer'

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

        # ECS Task/Services
        template.add_resource(self.ecs_wsgi_task(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))
        wsgi = self.ecs_wsgi_service(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        )
        template.add_resource(wsgi)
        template.add_resource(self.ecs_indexer_task(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))
        template.add_resource(self.ecs_indexer_service(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))
        template.add_resource(self.ecs_ingester_task(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))
        template.add_resource(self.ecs_ingester_service(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))

        # Add load balancer for WSGI
        # LB (old commented out)
        # template.add_resource(self.ecs_load_balancer())
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        target_group = self.ecs_lbv2_target_group()
        template.add_resource(target_group)
        template.add_resource(self.ecs_application_load_balancer_listener(target_group))
        template.add_resource(self.ecs_application_load_balancer())

        # Add outputs
        template.add_output(self.output_application_url())
        return template

    @staticmethod
    def ecs_cluster() -> Cluster:
        return Cluster(
            'CGAPDockerCluster'
        )

    @staticmethod
    def ecs_lb_certificate() -> Parameter:
        return Parameter(
            "CertId",
            Description='This is the SSL Cert to attach to the LB',
            Type='String'
        )

    @staticmethod
    def ecs_web_worker_port() -> Parameter:
        return Parameter(
            'WebWorkerPort',
            Description="Web worker container exposed port",
            Type="Number",
            Default=8000,  # port exposed by WSGI container
        )

    def ecs_container_security_group(self) -> SecurityGroup:
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
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=22,
                    ToPort=22,
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
            ]
        )

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ Allow both http, https traffic """
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
        )

    def ecs_application_load_balancer_listener(self, target_group: elbv2.TargetGroup) -> elbv2.Listener:
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
        logical_id = self.name.logical_id('ECSLB')
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

    def output_application_url(self) -> Output:
        """ Outputs URL to access WSGI. """
        return Output(
            'ECSApplicationURL',
            Description='URL of CGAP-Portal.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def ecs_lbv2_target_group(self) -> elbv2.TargetGroup:
        """ Creates LBv2 target group.
            Unused, should probably be used as current setup is 'classic'
        """
        return elbv2.TargetGroup(
            'TargetGroupApplication',
            HealthCheckPath='/health?format=json',
            HealthCheckProtocol='HTTP',
            HealthCheckTimeoutSeconds=20,
            Matcher=elbv2.Matcher(HttpCode='200'),
            Name='TargetGroupApplication',
            Port=Ref(self.ecs_web_worker_port()),
            TargetType='ip',
            Protocol='HTTP',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
        )

    @staticmethod
    def ecs_web_worker_cpu() -> Parameter:
        """ TODO: figure out how to best use
            Note that this value must match counts for underlying instance type!
            See vCPU values: https://aws.amazon.com/ec2/instance-types/c5/
        """
        return Parameter(
            'WebWorkerCPU',
            Description='Web worker CPU units',
            Type='Number',
            Default=256,
        )

    @staticmethod
    def ecs_web_worker_memory() -> Parameter:
        """ TODO: figure out how to best use
            Note that this value must match counts for underlying instance type!
            See Memory values: https://aws.amazon.com/ec2/instance-types/c5/
        """
        return Parameter(
            'WebWorkerMemory',
            Description='Web worker memory',
            Type='Number',
            Default=512,
        )

    def ecs_wsgi_task(self, ecr, log_group, role, cpus='256', mem='512', app_revision='latest') -> TaskDefinition:
        """ Defines the WSGI Task (serve HTTP requests).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param ecr: reference to ECR
            :param log_group: reference to log group
            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
        """
        return TaskDefinition(
            'CGAPWSGI',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=role,
            ExecutionRoleArn=role,
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='WSGI',
                    Essential=True,
                    Image=Join("", [
                        '645819926742.dkr.ecr.us-east-1.amazonaws.com/cgap-mastertest',  # XXX: get from args
                        ':',
                        app_revision,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(self.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-wsgi'
                        }
                    ),
                )
            ],
        )

    def ecs_wsgi_service(self, repo, log_group, role) -> Service:
        """ Defines the WSGI service (manages WSGI Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer

            Defined by the ECR Image tag 'latest'.
        """
        return Service(
            "CGAPWSGIService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['ECSLBListener'],  # XXX: Hardcoded, important!
            DesiredCount=2,
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='WSGI',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group()))
            ],
            LaunchType='FARGATE',
            TaskDefinition=Ref(self.ecs_wsgi_task(repo, log_group, role)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
        )

    @staticmethod
    def ecs_indexer_task(ecr, log_group, role, cpus='256', mem='512',
                         app_revision='latest-indexer') -> TaskDefinition:
        """ Defines the Indexer task (indexer app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param ecr: reference to ECR
            :param log_group: reference to log group
            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
        """
        return TaskDefinition(
            'CGAPIndexer',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=role,
            ExecutionRoleArn=role,
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Essential=True,
                    Image=Join('', [
                        '645819926742.dkr.ecr.us-east-1.amazonaws.com/cgap-mastertest',  # XXX: get from args
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-indexer'
                        }
                    ),
                )
            ],
        )

    def ecs_indexer_service(self, repo, log_group, role) -> Service:
        """ Defines the Indexer service (manages Indexer Tasks)
            TODO SQS autoscaling trigger?

            Defined by the ECR Image tag 'latest-indexer'.
        """
        return Service(
            "CGAPIndexerService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=1,
            LaunchType='FARGATE',
            TaskDefinition=Ref(self.ecs_indexer_task(repo, log_group, role)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
        )

    @staticmethod
    def ecs_ingester_task(ecr, log_group, role, cpus='256', mem='512', app_revision='latest-ingester') -> TaskDefinition:
        """ Defines the Ingester task (ingester app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param ecr: reference to ECR
            :param log_group: reference to log group
            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
        """
        return TaskDefinition(
            'CGAPIngester',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=role,
            ExecutionRoleArn=role,
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Ingester',
                    Essential=True,
                    Image=Join("", [
                        ecr,
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-ingester'
                        }
                    ),
                )
            ],
        )

    def ecs_ingester_service(self, repo, log_group, role) -> Service:
        """ Defines the Ingester service (manages Ingestion Tasks)

            Defined by the ECR Image tag 'latest-ingester'
            TODO push ingestion listener image
            TODO SQS Trigger?
        """
        return Service(
            "CGAPIngesterService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=1,
            LaunchType='FARGATE',
            TaskDefinition=Ref(self.ecs_ingester_task(repo, log_group, role)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
        )

    @staticmethod
    def ecs_deployment_task(ecr, log_group, role, cpus='256', mem='512',
                          app_revision='latest-deployment') -> TaskDefinition:
        """ Defines the Ingester task (ingester app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param ecr: reference to ECR
            :param log_group: reference to log group
            :param cpus: CPU value to assign to this task, default 256 (play with this value)
            :param mem: Memory amount for this task, default to 512 (play with this value)
            :param app_revision: Tag on ECR for the image we'd like to run
        """
        return TaskDefinition(
            'CGAPDeployment',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpus,
            Memory=mem,
            TaskRoleArn=role,
            ExecutionRoleArn=role,
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Deployment Action',
                    Essential=True,
                    Image=Join("", [
                        ecr,
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'cgap-deployment'
                        }
                    ),
                )
            ],
        )

    def ecs_deployment_service(self, repo, log_group, role) -> Service:
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
            TaskDefinition=Ref(self.ecs_deployment_task(repo, log_group, role)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
        )
