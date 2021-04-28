from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancing as elb,
    elasticloadbalancingv2 as elbv2,
    autoscaling,
    cloudformation,
    AWS_ACCOUNT_ID,
    AWS_STACK_ID,
    AWS_STACK_NAME,
    AWS_REGION,
    Base64,
    Template,
)
from troposphere.ecs import (
    Cluster,
    TaskDefinition,
    ContainerDefinition,
    Environment,
    LogConfiguration,
    PortMapping,
    Service,
    LoadBalancer
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
        template.add_parameter(self.ecs_container_instance_type())
        template.add_parameter(self.ecs_max_scale())
        template.add_parameter(self.ecs_desired_scale())
        # template.add_parameter(self.ecs_lb_certificate())  # TODO must be provisioned
        template.add_parameter(self.ecs_web_worker_memory())
        template.add_parameter(self.ecs_web_worker_cpu())
        template.add_parameter(self.ecs_container_ssh_key())  # TODO open ssh ports

        # ECS Components
        template.add_resource(self.ecs_cluster())
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_load_balancer())
        template.add_resource(self.ecs_container_security_group(  # container runs in private subnets
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
        ))
        template.add_resource(self.ecs_autoscaling_group(
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_INSTANCE_PROFILE)
        ))
        template.add_resource(self.ecs_container_instance_launch_configuration(
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_INSTANCE_PROFILE),
        ))

        # ECS Task/Services
        template.add_resource(self.ecs_wsgi_task(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP)
        ))
        template.add_resource(self.ecs_wsgi_service(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        ))
        # TODO enable, configure later
        # template.add_resource(self.ecs_indexer_task(
        #     self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
        #     self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP)
        # ))
        # template.add_resource(self.ecs_indexer_service(
        #     self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
        #     self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
        #     self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        # ))
        # template.add_resource(self.ecs_ingester_task(
        #     self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
        #     self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP)
        # ))
        # template.add_resource(self.ecs_ingester_service(
        #     self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
        #     self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
        #     self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        # ))
        return template

    @staticmethod
    def ecs_cluster():
        return Cluster(
            'CGAPDockerCluster'
        )

    @staticmethod
    def ecs_lb_certificate():
        return Parameter(
            "CertId",
            Description='This is the SSL Cert to attach to the LB',
            Type='String'
        )

    @staticmethod
    def ecs_desired_scale():
        return Parameter(
            'DesiredScale',
            Description='Desired container instances count',
            Type='Number',
            Default=1,
        )

    @staticmethod
    def ecs_max_scale():
        return Parameter(
            'MaxScale',
            Description='Maximum container instances count',
            Type='Number',
            Default=1,
        )

    @staticmethod
    def ecs_web_worker_port():
        return Parameter(
            'WebWorkerPort',
            Description="Web worker container exposed port",
            Type="Number",
            Default=8000,  # should work for us
        )

    @staticmethod
    def ecs_container_ssh_key():
        """ SSH key attached """
        return Parameter(
            'ECSContainerInstanceSSHAccessKey',
            Description='Name of an existing EC2 Keypair to enable SSH access '
                        'to the ECS container instances.',
            Type="String",
            Default='trial-ssh-key-01'  # XXX: needs passing
        )

    def ecs_lbv2_target_group(self) -> elbv2.TargetGroup:
        """ Creates LBv2 target group.
            Unused, should probably be used as current setup is 'classic'
        """
        return elbv2.TargetGroup(
            'TargetGroupWebWorker',
            HealthCheckProtocol='HTTP',
            HealthCheckTimeoutSeconds='20',
            HealthyThresholdCount='1',
            Matcher=elbv2.Matcher(HttpCode='200'),
            Name='WebWorkerTarget',
            Port=Ref(self.ecs_web_worker_port()),
            Protocol='HTTP',
            UnhealthyThresholdCount='1',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
        )

    def ecs_lb_security_group(self):
        """ Allow both http and https traffic (for now) """
        return SecurityGroup(
            "ECSLBSSLSecurityGroup",
            GroupDescription="Web load balancer security group.",
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort='443',
                    ToPort='443',
                    CidrIp='0.0.0.0/0',
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort='80',
                    ToPort='80',
                    CidrIp='0.0.0.0/0',
                ),
            ],
        )

    def ecs_load_balancer(self):
        return elb.LoadBalancer(
            'ECSLoadBalancer',
            Subnets=[  # LB lives in the public subnets
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            ],
            SecurityGroups=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP)],
            Listeners=[
                # Forward HTTPS on 443 to HTTP on the web port
                elb.Listener(
                    LoadBalancerPort=443,
                    InstanceProtocol='HTTP',
                    InstancePort=Ref(self.ecs_web_worker_port()),
                    Protocol='HTTP',  # TODO change to HTTPS
                    #  SSLCertificateId=Ref(self.ecs_lb_certificate()),
                    ),
                # Forward HTTP on 80 to HTTP on web port
                elb.Listener(
                    LoadBalancerPort=80,
                    InstanceProtocol='HTTP',
                    InstancePort=Ref(self.ecs_web_worker_port()),
                    Protocol='HTTP',
                )
            ],
            HealthCheck=elb.HealthCheck(
                Target=Join('', ['HTTP:', Ref(self.ecs_web_worker_port()), '/health?format=json']),
                HealthyThreshold='2',
                UnhealthyThreshold='2',
                Interval='120',
                Timeout='10',
            ),
        )

    @staticmethod
    def ecs_container_instance_type():
        return Parameter(
            'ContainerInstanceType',
            Description='The container instance type',
            Type="String",
            Default="c5.large",
            AllowedValues=['c5.large']  # configure more later
        )

    def ecs_container_security_group(self, public_subnet_cidr_1, public_subnet_cidr_2):
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
                    CidrIp=C4Network.CIDR_BLOCK,  # VPC CIDR?
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp='0.0.0.0/0',  # no idea if this is correct
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=22,
                    ToPort=22,
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
            ]
        )

    def ecs_container_instance_launch_configuration(self,
                                                    private_subnet_a,
                                                    private_subnet_b,
                                                    profile,
                                                    name='CGAPDockerWSGILaunchConfiguration'):
        """ Builds a launch configuration for the ecs container instance.
            This might be very wrong, but the general idea works for others.
        """
        return autoscaling.LaunchConfiguration(
            name,
            Metadata=autoscaling.Metadata(
                cloudformation.Init(dict(
                    config=cloudformation.InitConfig(
                        commands=dict(
                            register_cluster=dict(command=Join("", [
                                "#!/bin/bash\n",
                                # Register the cluster
                                "echo ECS_CLUSTER=",
                                Ref(self.ecs_cluster()),
                                " >> /etc/ecs/config\n",
                            ]))
                        ),
                        files=cloudformation.InitFiles({
                            "/etc/cfn/cfn-hup.conf": cloudformation.InitFile(
                                content=Join("", [
                                    "[main]\n",
                                    "template=",
                                    Ref(AWS_STACK_ID),
                                    "\n",
                                    "region=",
                                    Ref(AWS_REGION),
                                    "\n",
                                ]),
                                mode="000400",
                                owner="root",
                                group="root",
                            ),
                            "/etc/cfn/hooks.d/cfn-auto-reload.conf":
                            cloudformation.InitFile(
                                content=Join("", [
                                    "[cfn-auto-reloader-hook]\n",
                                    "triggers=post.update\n",
                                    "path=Resources.%s."
                                    % name,
                                    "Metadata.AWS::CloudFormation::Init\n",
                                    "action=/opt/aws/bin/cfn-init -v ",
                                    "         --template ",
                                    Ref(AWS_STACK_NAME),
                                    "         --resource %s"
                                    % name,
                                    "         --region ",
                                    Ref("AWS::Region"),
                                    "\n",
                                    "runas=root\n",
                                ])
                            )
                        }),
                        services=dict(
                            sysvinit=cloudformation.InitServices({
                                'cfn-hup': cloudformation.InitService(
                                    enabled=True,
                                    ensureRunning=True,
                                    files=[
                                        "/etc/cfn/cfn-hup.conf",
                                        "/etc/cfn/hooks.d/cfn-auto-reloader.conf",
                                    ]
                                ),
                            })
                        )
                    )
                ))
            ),
            SecurityGroups=[Ref(self.ecs_container_security_group(
                private_subnet_a, private_subnet_b,  # use private subnet for container
            ))],
            InstanceType=Ref(self.ecs_container_instance_type()),
            IamInstanceProfile=profile,
            ImageId=self.AMI,  # this is the AMI of the ec2 we want to use
            KeyName=Ref(self.ecs_container_ssh_key()),
            UserData=Base64(Join('', [
                "#!/bin/bash -xe\n",
                "yum install -y aws-cfn-bootstrap\n",

                "/opt/aws/bin/cfn-init -v ",
                "         --stack ", Ref(AWS_STACK_NAME),
                "         --resource %s " % name,
                "         --region ", Ref(AWS_REGION), "\n",
            ])),
        )

    @staticmethod
    def ecs_max_container_instances(max=1):
        return Parameter(
            'MaxScale',
            Description='Maximum container instances count',
            Type='Number',
            Default=max,  # XXX: How to best set this?
        )

    @staticmethod
    def ecs_desired_container_instances():
        return Parameter(
            'DesiredScale',
            Description='Desired container instances count',
            Type='Number',
            Default=1,
        )

    def ecs_autoscaling_group(self, private_subnet_a, private_subnet_b,
                              public_subnet_a, public_subnet_b, instance_profile,
                              name='CGAPDockerECSAutoscalingGroup'):
        """ Builds an autoscaling group for the EC2s """
        return autoscaling.AutoScalingGroup(
            name,
            VPCZoneIdentifier=[private_subnet_a, private_subnet_b],
            MinSize=1,
            MaxSize=1,
            DesiredCapacity=1,
            LaunchConfigurationName=Ref(self.ecs_container_instance_launch_configuration(public_subnet_a,
                                                                                         public_subnet_b,
                                                                                         instance_profile)),
            LoadBalancerNames=[Ref(self.ecs_load_balancer())],
            # Since one instance within the group is a reserved slot
            # for rolling ECS service upgrade, it's not possible to rely
            # on a "dockerized" `ELB` health-check, else this reserved
            # instance will be flagged as `unhealthy` and won't stop respawning'
            HealthCheckType="EC2",
            HealthCheckGracePeriod=300,

        )

    @staticmethod
    def ecs_web_worker_cpu():
        return Parameter(
            'WebWorkerCPU',
            Description='Web worker CPU units',
            Type='Number',
            Default=1024,  # 1 cpu
        )

    @staticmethod
    def ecs_web_worker_memory():
        return Parameter(
            'WebWorkerMemory',
            Description='Web worker memory',
            Type='Number',
            Default=2048,
        )

    def ecs_wsgi_task(self, ecr, log_group, app_revision='latest'):
        """ Defines the WSGI Task (serve HTTP requests) """
        return TaskDefinition(
            'CGAPWSGI',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='WSGI',
                    Cpu=Ref(self.ecs_web_worker_cpu()),
                    Memory=Ref(self.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        ecr,
                        ':',
                        app_revision,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(self.ecs_web_worker_port()),
                        HostPort=Ref(self.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    def ecs_indexer_task(self, ecr, log_group, app_revision='latest'):
        """ Defines the Indexer task (indexer app)
            TODO expand as needed
        """
        return TaskDefinition(
            'CGAPIndexer',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Cpu=Ref(self.ecs_web_worker_cpu()),
                    Memory=Ref(self.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        ecr,
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    def ecs_ingester_task(self, ecr, log_group, app_revision='latest'):
        """ Defines the Ingester task (ingester app)
            TODO expand as needed
        """
        return TaskDefinition(
            'CGAPIngester',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Cpu=Ref(self.ecs_web_worker_cpu()),
                    Memory=Ref(self.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        ecr,
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': log_group,
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    def ecs_wsgi_service(self, repo, log_group, role):
        """ Defines the WSGI service (manages WSGI Tasks) """
        return Service(
            "CGAPWSGIService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount=1,
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='WSGI',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    LoadBalancerName=Ref(self.ecs_load_balancer()))
            ],
            TaskDefinition=Ref(self.ecs_wsgi_task(repo, log_group)),
            Role=role,
        )

    def ecs_indexer_service(self, repo, log_group, role):
        """ Defines the Indexer service (manages Indexer Tasks)
            No open ports (for now)
            No LB
            TODO customize?
            TODO SQS trigger?
        """
        return Service(
            "CGAPIndexerService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount=1,
            TaskDefinition=Ref(self.ecs_indexer_task(repo, log_group)),
            Role=role,
        )

    def ecs_ingester_service(self, repo, log_group, role):
        """ Defines the Ingester service (manages Ingestion Tasks)
            No open ports (for now)
            No LB
            TODO customize?
            TODO SQS trigger?
        """
        return Service(
            "CGAPIngesterService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount=1,
            TaskDefinition=Ref(self.ecs_ingester_task(repo, log_group)),
            Role=role,
        )
