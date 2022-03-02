from troposphere import (
    Parameter, Join, Ref,
    AWS_REGION, Template, Output, GetAtt,
    elasticloadbalancingv2 as elbv2,
)
from troposphere.ecs import (
    Cluster, TaskDefinition, ContainerDefinition, LogConfiguration,
    PortMapping, Service, LoadBalancer, AwsvpcConfiguration, NetworkConfiguration,
    Environment, CapacityProviderStrategyItem, SCHEDULING_STRATEGY_REPLICA,  # use for Fargate
)
from dcicutils.cloudformation_utils import camelize
from ..base import ConfigManager
from ..constants import Settings
from .ecs import C4ECSApplicationExports, C4ECSApplication
from .network import C4NetworkExports
from .ecr import C4ECRExports
from .iam import C4IAMExports
from .logging import C4LoggingExports
from .fourfront_ecs import FourfrontApplicationTypes


class FourfrontECSBlueGreen(C4ECSApplication):
    """ Configures two ECS clusters in a blue/green fashion.
        Note that this only orchestrates the ECS component - datastore is still TODO.
    """
    VPC_SQS_URL = 'https://sqs.us-east-1.amazonaws.com/'
    IMAGE_TAG_BLUE = 'blue'
    IMAGE_TAG_GREEN = 'green'
    BLUE_TERMINAL = 'blue'
    GREEN_TERMINAL = 'green'

    def build_template(self, template: Template) -> Template:
        """ Builds the template containing two ECS environments. """
        if ConfigManager.get_config_setting(Settings.APP_DEPLOYMENT, '') != 'bg':
            raise Exception('Tried to build Fourfront blue/green but APP_DEPLOYMENT '
                            'is not "bg"!')

        # Add network parameters
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

        # Standard params
        template.add_parameter(self.ecs_web_worker_port())

        # Add Security Groups
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())

        # clusters
        blue_cluster = self.ecs_cluster(postfix=self.BLUE_TERMINAL)
        template.add_resource(blue_cluster)
        green_cluster = self.ecs_cluster(postfix=self.GREEN_TERMINAL)
        template.add_resource(green_cluster)

        # Target Groups
        # Provisioned now so refs can be passed to API services
        target_group_green = self.ecs_lbv2_target_group_green()
        target_group_blue = self.ecs_lbv2_target_group_blue()
        template.add_resource(target_group_green)
        template.add_resource(target_group_blue)

        # ECS Tasks/Services
        # This dictionary structure just collects all necessary components for building the
        # symmetric blue/green cleanly - core components include:
        #   * ECS Cluster
        #   * Target Group
        #   * Identity (GAC)
        #   * Log Group
        tags = {
            'blue': (blue_cluster, target_group_blue,
                     ConfigManager.get_config_setting(Settings.BLUE_IDENTITY),
                     C4LoggingExports.APPLICATION_LOG_GROUP_BLUE),
            'green': (green_cluster, target_group_green,
                      ConfigManager.get_config_setting(Settings.GREEN_IDENTITY),
                      C4LoggingExports.APPLICATION_LOG_GROUP_GREEN)
        }
        for tag, (cluster, target_group, identity, log_export) in tags.items():
            # Portal task/service
            portal_task = self.ecs_portal_task(image_tag=tag, log_group_export=log_export, identity=identity)
            template.add_resource(portal_task)
            portal_service = self.ecs_portal_service(cluster_ref=Ref(cluster),
                                                     target_group_ref=Ref(target_group), image_tag=tag,
                                                     task_definition=Ref(portal_task))
            template.add_resource(portal_service)

            # Indexer task/service
            indexer_task = self.ecs_indexer_task(image_tag=tag, log_group_export=log_export, identity=identity)
            template.add_resource(indexer_task)
            indexer_service = self.ecs_indexer_service(cluster_ref=Ref(cluster), image_tag=tag,
                                                       task_definition=Ref(indexer_task))
            template.add_resource(indexer_service)

            # Deployment tasks
            template.add_resource(self.ecs_deployment_task(image_tag=tag, log_group_export=log_export,
                                                           identity=identity, initial=True))
            template.add_resource(self.ecs_deployment_task(image_tag=tag, log_group_export=log_export,
                                                           identity=identity))

        # Load Balancers
        blue_lb = self.ecs_application_load_balancer_blue()
        template.add_resource(blue_lb)
        green_lb = self.ecs_application_load_balancer_green()
        template.add_resource(green_lb)
        template.add_resource(self.ecs_application_load_balancer_listener(target_group_blue,
                                                                          logical_id='LBListenerBlue',
                                                                          lb_ref=Ref(blue_lb)))
        template.add_resource(self.ecs_application_load_balancer_listener(target_group_green,
                                                                          logical_id='LBListenerGreen',
                                                                          lb_ref=Ref(green_lb)))

        # Add indexing Cloudwatch Alarms
        # These alarms are meant to trigger symmetric scaling actions in response to
        # sustained indexing load - the specifics of the autoscaling is left for
        # manual configuration by the orchestrator according to their needs
        template.add_resource(self.indexer_queue_empty_alarm(postfix=self.BLUE_TERMINAL))
        template.add_resource(self.indexer_queue_depth_alarm(postfix=self.BLUE_TERMINAL))
        template.add_resource(self.indexer_queue_empty_alarm(postfix=self.GREEN_TERMINAL))
        template.add_resource(self.indexer_queue_depth_alarm(postfix=self.GREEN_TERMINAL))

        # Output URLs
        template.add_output(self.output_blue_application_url())
        template.add_output(self.output_green_application_url())

        return template

    def output_blue_application_url(self, env=None) -> Output:
        """ Outputs URL to access portal. """
        env = env or (ConfigManager.get_config_setting(Settings.ENV_NAME) + self.BLUE_TERMINAL)
        return Output(
            C4ECSApplicationExports.output_application_url_key(env),
            Description='URL of Fourfront-Portal-Blue.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer_blue(), 'DNSName')])
        )

    def output_green_application_url(self, env=None) -> Output:
        """ Outputs URL to access portal. """
        env = env or (ConfigManager.get_config_setting(Settings.ENV_NAME) + self.GREEN_TERMINAL)
        return Output(
            C4ECSApplicationExports.output_application_url_key(env),
            Description='URL of Fourfront-Portal-Green.',
            Value=Join('', ['http://', GetAtt(self.ecs_application_load_balancer_green(), 'DNSName')])
        )

    def ecs_cluster(self, postfix=None):
        """ Defines an ECS cluster """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Cluster(
            # Always use env name for cluster
            camelize(env_name + (postfix if postfix else '')),
            CapacityProviders=['FARGATE', 'FARGATE_SPOT'],
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_application_load_balancer_listener(self, target_group: elbv2.TargetGroup,
                                               logical_id=None, lb_ref=None):
        """ Load balancer listener, forwards traffic to portal tasks """
        return elbv2.Listener(
            self.name.logical_id(logical_id) if logical_id else self.name.logical_id('LBListener'),
            Port=80,
            Protocol='HTTP',
            LoadBalancerArn=lb_ref if lb_ref else Ref(self.ecs_application_load_balancer_blue()),
            DefaultActions=[
                elbv2.Action(Type='forward', TargetGroupArn=Ref(target_group))
            ]
        )

    def ecs_lbv2_target_group_blue(self) -> elbv2.TargetGroup:
        return self.ecs_lbv2_target_group(name='TargetGroupApplicationBlue')

    def ecs_lbv2_target_group_green(self) -> elbv2.TargetGroup:
        return self.ecs_lbv2_target_group(name='TargetGroupApplicationGreen')

    def ecs_application_load_balancer_blue(self):
        """ Defines the blue application load balancer. """
        return self.ecs_application_load_balancer(terminal=self.BLUE_TERMINAL)

    def ecs_application_load_balancer_green(self):
        """ Defines the green application load balancer. """
        return self.ecs_application_load_balancer(terminal=self.GREEN_TERMINAL)

    def ecs_portal_task(self, cpu='4096', mem='8192', image_tag='',
                        log_group_export=None, identity=None) -> TaskDefinition:
        """ Defines the portal Task (serve HTTP requests).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html
            Note that not much has changed for the FF version.

            :param cpu: CPU value to assign to this task
            :param mem: Memory amount for this task
            :param image_tag: image tag to use for this task
            :param log_group_export: log group export name to use
            :param identity: name of secret containing the identity information for this environment
        """
        return TaskDefinition(
            f'Fourfront{image_tag}Portal',
            RequiresCompatibilities=['FARGATE'],
            Cpu=ConfigManager.get_config_setting(Settings.ECS_WSGI_CPU, cpu),
            Memory=ConfigManager.get_config_setting(Settings.ECS_WSGI_MEMORY, mem),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name=f'{image_tag}portal',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG if image_tag is None else image_tag,
                    ]),
                    PortMappings=[PortMapping(
                        ContainerPort=Ref(self.ecs_web_worker_port()),
                    )],
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group':
                                self.LOGGING_EXPORTS.import_value(
                                    C4LoggingExports.APPLICATION_LOG_GROUP if not log_group_export else log_group_export
                                ),
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

    def ecs_portal_service(self, cluster_ref=None, target_group_ref=None, image_tag='',
                           task_definition=None, concurrency=8) -> Service:
        """ Defines the portal service (manages portal Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer

            Defined by the ECR Image tag 'latest'.

            :param cluster_ref: reference to cluster to associate with this service
            :param target_group_ref: reference to target group, will fallback to standalone
            :param image_tag: used to postfix various references if passed
            :param task_definition: reference to task definition to use
            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 8, approximately matching our current resources.
        """  # noQA - ignore line length issues
        return Service(
            f'Fourfront{image_tag}PortalService',
            Cluster=Ref(self.ecs_cluster()) if not cluster_ref else cluster_ref,
            DependsOn=[self.name.logical_id(f'LBListener{image_tag.capitalize()}')],
            DesiredCount=ConfigManager.get_config_setting(Settings.ECS_WSGI_COUNT, concurrency),
            LoadBalancers=[
                LoadBalancer(
                    ContainerName=f'{image_tag}portal',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group()) if not target_group_ref else target_group_ref)
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
            TaskDefinition=Ref(self.ecs_portal_task()) if not task_definition else task_definition,
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in C4NetworkExports.PRIVATE_SUBNETS
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_indexer_task(self, cpu='256', memory='512', image_tag='',
                         log_group_export=None, identity=None) -> TaskDefinition:
        """ Defines the Indexer task (indexer app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task, default 256 (play with this value)
            :param memory: Memory amount for this task, default to 512 (play with this value)
            :param image_tag: image tag to use for this task, latest by default
            :param log_group_export: log group export name to use
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
        """
        return TaskDefinition(
            f'Fourfront{image_tag}Indexer',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpu or ConfigManager.get_config_setting(Settings.ECS_INDEXER_CPU, self.DEFAULT_INDEXER_CPU),
            Memory=memory or ConfigManager.get_config_setting(Settings.ECS_INDEXER_MEMORY, self.DEFAULT_INDEXER_MEMORY),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            ContainerDefinitions=[
                ContainerDefinition(
                    Name=f'{image_tag}Indexer',
                    Essential=True,
                    Image=Join('', [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        image_tag if image_tag else self.IMAGE_TAG,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group':
                                self.LOGGING_EXPORTS.import_value(
                                    C4LoggingExports.APPLICATION_LOG_GROUP if not log_group_export else log_group_export
                                ),
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

    def ecs_indexer_service(self, cluster_ref=None, image_tag='',
                            task_definition=None, concurrency=4) -> Service:
        """ Defines the Indexer service (manages Indexer Tasks)

            :param cluster_ref: reference to cluster to associate with this service
            :param task_definition: reference to task definition to use
            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 4, approximately matching our current resources.
        """
        return Service(
            f'Fourfront{image_tag}IndexerService',
            Cluster=Ref(self.ecs_cluster()) if not cluster_ref else cluster_ref,
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
            TaskDefinition=Ref(self.ecs_indexer_task()) if not task_definition else task_definition,
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in C4NetworkExports.PRIVATE_SUBNETS
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_deployment_task(self, cpu='1024', memory='2048', image_tag='',
                            log_group_export=None, identity=None, initial=False) -> TaskDefinition:
        """ Defines the Deployment task (run deployment action).
            Meant to be run manually from ECS Console (or from foursight), so no associated service.

            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task
            :param memory: Memory amount for this task
            :param image_tag: image tag to use for this task, latest by default
            :param log_group_export: log group export name to use
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
            :param initial: boolean saying whether this task is intended to do the first deploy.
                            If it is, the environment variable INITIAL_DEPLOYMENT gets set to True,
                            causing a different initialization sequence.
        """
        return TaskDefinition(
            f'Fourfront{image_tag}InitialDeployment' if initial else f'Fourfront{image_tag}Deployment',
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
                    Name=f'{image_tag}DeploymentAction',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        image_tag if image_tag else self.IMAGE_TAG,
                    ]),
                    LogConfiguration=LogConfiguration(
                        LogDriver='awslogs',
                        Options={
                            'awslogs-group':
                                self.LOGGING_EXPORTS.import_value(
                                    C4LoggingExports.APPLICATION_LOG_GROUP if not log_group_export else log_group_export
                                ),
                            'awslogs-region': Ref(AWS_REGION),
                            'awslogs-stream-prefix': 'fourfront-initial-deployment' if initial else 'fourfront-deployment',
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
