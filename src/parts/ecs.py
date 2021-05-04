from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancing as elb,
    elasticloadbalancingv2 as elbv2,  # Listener, Action, RedirectConfig
    autoscaling,
    cloudformation,
    AWS_ACCOUNT_ID,
    AWS_STACK_ID,
    AWS_STACK_NAME,
    AWS_REGION,
    Base64,
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
        template.add_parameter(self.ecs_container_instance_type())
        template.add_parameter(self.ecs_max_scale())
        template.add_parameter(self.ecs_desired_scale())
        # template.add_parameter(self.ecs_lb_certificate())  # TODO must be provisioned
        template.add_parameter(self.ecs_web_worker_memory())
        template.add_parameter(self.ecs_web_worker_cpu())
        template.add_parameter(self.ecs_container_ssh_key())  # TODO open ssh ports

        # ECS
        template.add_resource(self.ecs_cluster())

        # ECS Task/Services
        template.add_resource(self.ecs_wsgi_task(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP)
        ))
        wsgi = self.ecs_wsgi_service(
            self.ECR_EXPORTS.import_value(C4ECRExports.ECR_REPO_URL),
            self.LOGGING_EXPORTS.import_value(C4LoggingExports.CGAP_APPLICATION_LOG_GROUP),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
        )
        template.add_resource(wsgi)
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

        # Add load balancer for WSGI
        # LB (old commented out)
        # template.add_resource(self.ecs_load_balancer())
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        target_group = self.ecs_lbv2_target_group()
        template.add_resource(target_group)
        template.add_resource(self.ecs_application_load_balancer_listener(target_group))
        template.add_resource(self.ecs_application_load_balancer())

        # Add Autoscaling group, EC2 Container launch configuration
        template.add_resource(self.ecs_autoscaling_group(
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_INSTANCE_PROFILE),
            wsgi
        ))
        template.add_resource(self.ecs_container_instance_launch_configuration(
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
            self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
            self.IAM_EXPORTS.import_value(C4IAMExports.ECS_INSTANCE_PROFILE),
        ))

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
    def ecs_desired_scale() -> Parameter:
        return Parameter(
            'DesiredScale',
            Description='Desired container instances count',
            Type='Number',
            Default=1,
        )

    @staticmethod
    def ecs_max_scale() -> Parameter:
        return Parameter(
            'MaxScale',
            Description='Maximum container instances count',
            Type='Number',
            Default=1,
        )

    @staticmethod
    def ecs_web_worker_port() -> Parameter:
        return Parameter(
            'WebWorkerPort',
            Description="Web worker container exposed port",
            Type="Number",
            Default=8000,  # should work for us
        )

    @staticmethod
    def ecs_container_ssh_key() -> Parameter:
        """ SSH key attached """
        return Parameter(
            'ECSContainerInstanceSSHAccessKey',
            Description='Name of an existing EC2 Keypair to enable SSH access '
                        'to the ECS container instances.',
            Type="String",
            Default='trial-ssh-key-01'  # XXX: needs passing
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
        return Output(
            'ECSApplicationURL',
            Description='URL of CGAP-Portal.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def ecs_load_balancer(self) -> elb.LoadBalancer:
        """ DEPRECATED.
            Classic load balancer. Does not support >1 host per container.
        """
        return elb.LoadBalancer(
            'ECSLoadBalancer',
            Subnets=[  # LB lives in the public subnets
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            ],
            SecurityGroups=[Ref(self.ecs_lb_security_group())],
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
    def ecs_container_instance_type() -> Parameter:
        return Parameter(
            'ContainerInstanceType',
            Description='The container instance type',
            Type='String',
            Default='c5.large',
            AllowedValues=['c5.large']  # configure more later
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
            TargetType='instance',
            Protocol='HTTP',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
        )

    def ecs_container_instance_launch_configuration(self,
                                                    private_subnet_a,
                                                    private_subnet_b,
                                                    profile,
                                                    name='CGAPDockerWSGILaunchConfiguration') -> autoscaling.LaunchConfiguration:
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
                                " >> /etc/ecs/ecs.config\n",
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
                                    "         --stack ",
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
            SecurityGroups=[Ref(self.ecs_container_security_group())],
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
    def ecs_max_container_instances(max=1) -> Parameter:
        return Parameter(
            'MaxScale',
            Description='Maximum container instances count',
            Type='Number',
            Default=max,  # XXX: How to best set this?
        )

    @staticmethod
    def ecs_desired_container_instances() -> Parameter:
        return Parameter(
            'DesiredScale',
            Description='Desired container instances count',
            Type='Number',
            Default=1,
        )

    def ecs_autoscaling_group(self, private_subnet_a, private_subnet_b,
                              public_subnet_a, public_subnet_b, instance_profile, wsgi,
                              name='CGAPDockerECSAutoscalingGroup') -> autoscaling.AutoScalingGroup:
        """ Builds an autoscaling group for the EC2s """
        return autoscaling.AutoScalingGroup(
            name,
            VPCZoneIdentifier=[private_subnet_a, private_subnet_b],
            MinSize='1',
            MaxSize='1',
            DesiredCapacity='1',
            LaunchConfigurationName=Ref(self.ecs_container_instance_launch_configuration(public_subnet_a,
                                                                                         public_subnet_b,
                                                                                         instance_profile)),
            TargetGroupARNs=[Ref(self.ecs_lbv2_target_group())],
            HealthCheckType='EC2',
            HealthCheckGracePeriod=300,
        )

    @staticmethod
    def ecs_web_worker_cpu() -> Parameter:
        """ GLOBAL CPU count for container runtimes (EC2s).
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
        """ GLOBAL Memory count for container runtimes (EC2s).
            Note that this value must match counts for underlying instance type!
            See Memory values: https://aws.amazon.com/ec2/instance-types/c5/
        """
        return Parameter(
            'WebWorkerMemory',
            Description='Web worker memory',
            Type='Number',
            Default=512,
        )

    def ecs_wsgi_task(self, ecr, log_group, cpus='256', mem='512', app_revision='latest') -> TaskDefinition:
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
                        HostPort=0,  # dynamic port mappings
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

    def ecs_indexer_task(self, ecr, log_group, cpus='256', mem='512', app_revision='latest-indexer') -> TaskDefinition:
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
                        }
                    ),
                )
            ],
            Cpu=cpus,
            Memory=mem
        )

    def ecs_ingester_task(self, ecr, log_group, cpus='256', mem='512', app_revision='latest') -> TaskDefinition:
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
            ContainerDefinitions=[
                ContainerDefinition(
                    Name='Indexer',
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
                        }
                    ),
                )
            ],
            Cpu=cpus,
            Memory=mem
        )

    def ecs_wsgi_service(self, repo, log_group, role) -> Service:
        """ Defines the WSGI service (manages WSGI Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer
        """
        return Service(
            "CGAPWSGIService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup', 'ECSLBListener'],  # XXX: Hardcoded, important!
            DesiredCount=2,
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='WSGI',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group()))
            ],
            LaunchType='FARGATE',
            TaskDefinition=Ref(self.ecs_wsgi_task(repo, log_group)),
            Role=role,
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                             self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
        )

    def ecs_indexer_service(self, repo, log_group, role) -> Service:
        """ Defines the Indexer service (manages Indexer Tasks)
            TODO SQS Trigger?
        """
        return Service(
            "CGAPIndexerService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount=1,
            TaskDefinition=Ref(self.ecs_indexer_task(repo, log_group)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
        )

    def ecs_ingester_service(self, repo, log_group, role) -> Service:
        """ Defines the Ingester service (manages Ingestion Tasks)
            TODO push ingestion listener image
            TODO SQS Trigger?
        """
        return Service(
            "CGAPIngesterService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=['CGAPDockerECSAutoscalingGroup'],  # XXX: Hardcoded
            DesiredCount=1,
            TaskDefinition=Ref(self.ecs_ingester_task(repo, log_group)),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
        )
