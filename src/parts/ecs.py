from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancing as elb,
    autoscaling,
    cloudformation,
    AWS_ACCOUNT_ID,
    AWS_STACK_ID,
    AWS_STACK_NAME,
    AWS_REGION,
    Base64,
    Template
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
from src.parts.network import C4NetworkExports


class QCECSApplication(C4Part):
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

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            QCNetworkExports.REFERENCE_PARAM_KEY,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # TODO Adds ECR Stack Parameter
        # TODO Adds IAM Stack Parameter

        # ECS Params
        template.add_parameter(self.ecs_web_worker_port())
        template.add_parameter(self.ecs_container_instance_type())

        # ECS Components
        template.add_resource(self.ecs_cluster())
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_load_balancer())
        template.add_resource(self.ecs_container_security_group(  # container runs in private subnets
            QCNetworkExports.import_value(QCNetworkExports.PRIVATE_SUBNET_A),
            QCNetworkExports.import_value(QCNetworkExports.PRIVATE_SUBNET_B),
        ))
        template.add_resource(self.ecs_autoscaling_group(
            QCNetworkExports.import_value(QCNetworkExports.PRIVATE_SUBNET_A),
            QCNetworkExports.import_value(QCNetworkExports.PRIVATE_SUBNET_B),
            QCNetworkExports.import_value(QCNetworkExports.PUBLIC_SUBNET_A),
            QCNetworkExports.import_value(QCNetworkExports.PUBLIC_SUBNET_B),
            # TODO missing output val here for ECS IAM instance profile
        ))

        # ECS Task/Services
        template.add_resource(self.ecs_wsgi_task())
        template.add_resource(self.ecs_wsgi_service())
        template.add_resource(self.ecs_indexer_task())
        template.add_resource(self.ecs_indexer_service())
        template.add_resource(self.ecs_ingester_task())
        template.add_resource(self.ecs_ingester_service())

        return template

    @classmethod
    def ecs_cluster(cls):
        return Cluster(
            'CGAPDockerCluster'
        )

    @classmethod
    def ecs_lb_certificate(cls):
        return Parameter(
            "CertId",
            Description='This is the SSL Cert to attach to the LB',
            Type='String'
        )

    @classmethod
    def ecs_web_worker_port(cls):
        return Parameter(
            'WebWorkerPort',
            Description="Web worker container exposed port",
            Type="Number",
            Default="8000",  # should work for us
        )

    @classmethod
    def ecs_lb_security_group(cls):
        return SecurityGroup(
            "ECSLBSSLSecurityGroup",
            GroupDescription="Web load balancer security group.",
            VpcId=cls.cf_id('VPC'),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort="443",
                    ToPort="443",
                    CidrIp='0.0.0.0/0',
                ),
            ],
        )

    @classmethod
    def ecs_load_balancer(cls):
        return elb.LoadBalancer(
            'ECSLoadBalancer',
            Subnets=[
                # TODO How to specify the 2 public subnets?
            ],
            SecurityGroups=[Ref(cls.ecs_lb_security_group())],
            Listeners=[elb.Listener(
                LoadBalancerPort=443,
                InstanceProtocol='HTTP',
                InstancePort=Ref(cls.ecs_web_worker_port()),
                Protocol='HTTPS',
                SSLCertificateId=Ref(cls.ecs_lb_certificate()),
            )],
            HealthCheck=elb.HealthCheck(
                Target=Join("", ["HTTP:", Ref(cls.ecs_web_worker_port()), "/health"]),
                HealthyThreshold="2",
                UnhealthyThreshold="2",
                Interval="120",
                Timeout="10",
            ),
        )

    @classmethod
    def ecs_container_instance_type(cls):
        return Parameter(
            'ContainerInstanceType',
            Description='The container instance type',
            Type="String",
            Default="c5.large",
            AllowedValues=['c5.large']  # configure more later
        )

    @classmethod
    def ecs_container_security_group(cls, public_subnet_cidr_1, public_subnet_cidr_2):
        return SecurityGroup(
            'ContainerSecurityGroup',
            GroupDescription='Container Security Group.',
            VpcId=cls.cf_id('VPC'),
            SecurityGroupIngress=[
                # HTTP from web public subnets
                SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort=Ref(cls.ecs_web_worker_port()),
                    ToPort=Ref(cls.ecs_web_worker_port()),
                    CidrIp=public_subnet_cidr_1,
                ),
                SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort=Ref(cls.ecs_web_worker_port()),
                    ToPort=Ref(cls.ecs_web_worker_port()),
                    CidrIp=public_subnet_cidr_2,
                ),
            ]
        )

    @classmethod
    def ecs_container_instance_configuration(cls,
                                             public_subnet_a,
                                             public_subnet_b,
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
                                Ref(cls.ecs_cluster()),
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
            SecurityGroups=[Ref(cls.ecs_container_security_group(
                '10.2.5.0/24', '10.2.7.0/24'  # TODO get via arguments
            ))],
            InstanceType=Ref(cls.ecs_container_instance_type()),
            IamInstanceProfile=Ref(profile),
            UserData=Base64(Join('', [
                "#!/bin/bash -xe\n",
                "yum install -y aws-cfn-bootstrap\n",

                "/opt/aws/bin/cfn-init -v ",
                "         --template ", Ref(AWS_STACK_NAME),
                "         --resource %s " % name,
                "         --region ", Ref(AWS_REGION), "\n",
            ])),
        )

    @staticmethod
    def ecs_max_container_instances(max='1'):
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
            Default='1',
        )

    @classmethod
    def ecs_autoscaling_group(cls, private_subnet_a, private_subnet_b,
                              public_subnet_a, public_subnet_b, instance_profile,
                              name='CGAPDockerECSAutoscalingGroup'):
        """ Builds an autoscaling group for the EC2s """
        return autoscaling.AutoScalingGroup(
            name,
            VPCZoneIdentifier=[Ref(private_subnet_a), Ref(private_subnet_b)],
            MinSize=Ref(cls.ecs_desired_container_instances()),
            MaxSize=Ref(cls.ecs_max_container_instances()),
            DesiredCapacity=Ref(cls.ecs_desired_container_instances()),
            LaunchConfigurationName=Ref(cls.ecs_container_instance_configuration(public_subnet_a,
                                                                                 public_subnet_b,
                                                                                 instance_profile)),
            LoadBalancerNames=[Ref(cls.ecs_load_balancer())],
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
            Default='1024',  # 1 cpu
        )

    @staticmethod
    def ecs_web_worker_memory():
        return Parameter(
            'WebWorkerMemory',
            Description='Web worker memory',
            Type='Number',
            Default='2048',
        )

    @classmethod
    def ecs_wsgi_task(cls, ecr, log_group, app_revision='latest'):
        """ Defines the WSGI Task (serve HTTP requests) """
        return TaskDefinition(
            'CGAPWSGI',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='WSGI',
                    Cpu=Ref(cls.ecs_web_worker_cpu()),
                    Memory=Ref(cls.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        Ref(ecr),
                        ':',
                        app_revision,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(cls.ecs_web_worker_port()),
                        HostPort=Ref(cls.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': Ref(log_group),
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    @classmethod
    def ecs_indexer_task(cls, ecr, log_group, app_revision='latest'):
        """ Defines the Indexer task (indexer app)
            TODO expand as needed
        """
        return TaskDefinition(
            'CGAPIndexer',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Cpu=Ref(cls.ecs_web_worker_cpu()),
                    Memory=Ref(cls.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        Ref(ecr),
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': Ref(log_group),
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    @classmethod
    def ecs_ingester_task(cls, ecr, log_group, app_revision='latest'):
        """ Defines the Ingester task (ingester app)
            TODO expand as needed
        """
        return TaskDefinition(
            'CGAPIngester',
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
                    Cpu=Ref(cls.ecs_web_worker_cpu()),
                    Memory=Ref(cls.ecs_web_worker_memory()),
                    Essential=True,
                    Image=Join("", [
                        Ref(AWS_ACCOUNT_ID),
                        '.dkr.ecr.',
                        Ref(AWS_REGION),
                        '.amazonaws.com/',
                        Ref(ecr),
                        ':',
                        app_revision,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group': Ref(log_group),
                            'awslogs-region': Ref(AWS_REGION),
                        }
                    ),
                )
            ],
        )

    @classmethod
    def ecs_wsgi_service(cls, repo, log_group, role):
        """ Defines the WSGI service (manages WSGI Tasks) """
        return Service(
            "CGAPWSGIService",
            Cluster=Ref(cls.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount='1',
            LoadBalancers=[LoadBalancer(
                ContainerName='WSGILB',
                ContainerPort=Ref(cls.ecs_web_worker_port()),
                LoadBalancerName=Ref(cls.ecs_load_balancer()),
            )],
            TaskDefinition=Ref(cls.ecs_wsgi_task(repo, log_group)),
            Role=Ref(role),
        )

    @classmethod
    def ecs_indexer_service(cls, repo, log_group, role):
        """ Defines the Indexer service (manages Indexer Tasks)
            No open ports (for now)
            No LB
            TODO customize?
            TODO SQS trigger?
        """
        return Service(
            "CGAPIndexerService",
            Cluster=Ref(cls.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount='1',
            TaskDefinition=Ref(cls.ecs_indexer_task(repo, log_group)),
            Role=Ref(role),
        )

    @classmethod
    def ecs_ingester_service(cls, repo, log_group, role):
        """ Defines the Ingester service (manages Ingestion Tasks)
            No open ports (for now)
            No LB
            TODO customize?
            TODO SQS trigger?
        """
        return Service(
            "CGAPIngesterService",
            Cluster=Ref(cls.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount='1',
            TaskDefinition=Ref(cls.ecs_ingester_task(repo, log_group)),
            Role=Ref(role),
        )
