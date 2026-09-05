import json
from dcicutils.cloudformation_utils import make_required_key_for_ecs_application_url, camelize
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
from troposphere.cloudwatch import Alarm, MetricDimension
from troposphere.ec2 import SecurityGroup, SecurityGroupRule
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
    # CrowdStrike Falcon sidecar support (see _crowdstrike_task_kwargs). NOTE: troposphere.ecs.Secret
    # is distinct from troposphere.secretsmanager.Secret used elsewhere -- kept unaliased here.
    Volume,
    Host,
    MountPoint,
    ContainerDependency,
    Secret,
)
from ..base import ConfigManager
from ..constants import Settings
from ..exports import C4Exports
from ..part import C4Part
from .network import C4NetworkExports, C4Network
from .ecr import C4ECRExports
from .iam import C4IAMExports
from .logging import C4LoggingExports
from .appconfig import C4AppConfigExports


class C4ECSApplicationTypes:
    """ Defines the set of possible application types - these identifiers are resolved
        in the production entrypoint.sh to direct to the correct entrypoint.

        Note that this config is for CGAP orchestrations.
    """
    PORTAL = 'portal'
    INDEXER = 'indexer'
    INGESTER = 'ingester'
    DEPLOYMENT = 'deployment'


class C4ECSApplicationExports(C4Exports):
    """ Holds ECS export metadata. """

    @classmethod
    def output_application_url_key(cls, env_name):
        # dcicutils.cloudformation_utils depends on this for now, so be careful changing it. -kmp 16-Aug-2021
        # return f'ECSApplicationURL{dehyphenate(env_name)}'
        return make_required_key_for_ecs_application_url(env_name)

    @classmethod
    def get_application_url(cls, env_name):
        # e.g., applicaton_url_key = 'ECSApplicationURLcgapmastertest' for cgap-mastertest
        application_url_key = cls.output_application_url_key(env_name)
        application_url = ConfigManager.find_stack_output(application_url_key, value_only=True)
        return application_url

    def __init__(self):
        # The intention here is that Beanstalk/ECS stacks will use these outputs and reduce manual configuration.
        parameter = 'ECSStackNameParameter'
        super().__init__(parameter)


class C4ECSApplication(C4Part):
    """ Configures the ECS Cluster Application for CGAP
        This class contains everything necessary for running CGAP on ECS, including:
            * Cluster
            * Application Load Balancer (Fargate compatible)
            * ECS Tasks/Services
                * portal
                * Indexer
                * Ingester
            * TODO: Autoscaling
    """
    NETWORK_EXPORTS = C4NetworkExports()
    ECR_EXPORTS = C4ECRExports()
    IAM_EXPORTS = C4IAMExports()
    LOGGING_EXPORTS = C4LoggingExports()
    APPCONFIG_EXPORTS = C4AppConfigExports()  # for the Falcon CID secret ARN (CrowdStrike)

    # --- CrowdStrike Falcon container sensor (sidecar) --------------------------------------------
    # Physical names/values demonstrated by the vendor task definition; kept as symbols so the
    # sidecar wiring stays consistent across every task variant (and matches the captain's example).
    CROWDSTRIKE_VOLUME_NAME = 'crowdstrike-falcon-volume'
    FALCON_SIDECAR_CONTAINER_NAME = 'falcon-container'
    # Vendor env var name the falcon sensor reads the CID from; injected from Secrets Manager.
    FALCON_CID_SECRET_ENV_NAME = 'FALCONCTL_OPT_FALCONCTL_CID'
    FALCON_BACKEND_ENV_NAME = 'FALCONCTL_OPT_BACKEND'
    DEFAULT_CROWDSTRIKE_MOUNT_PATH = '/tmp/CrowdStrike'
    DEFAULT_CROWDSTRIKE_BACKEND = 'bpf'
    DEFAULT_FALCON_SENSOR_IMAGE_TAG = 'latest'
    # The application container depends on the sidecar finishing its volume-prep and exiting 0.
    # SUCCESS is correct for a prepare-and-exit init sidecar (the vendor image is non-essential and
    # runs to completion). If the sensor image ever runs persistently this must revisit COMPLETE,
    # else wrapped tasks would deadlock in PENDING -- see docs/source/crowdstrike.rst.
    FALCON_SIDECAR_DEPENDS_CONDITION = 'SUCCESS'

    AMI = 'ami-0be13a99cd970f6a9'  # latest amazon linux 2 ECS optimized
    LB_NAME = 'AppLB'
    IMAGE_TAG = ConfigManager.get_config_setting(Settings.ECS_IMAGE_TAG, 'latest')
    LEGACY_DEFAULT_IDENTITY = 'dev/beanstalk/cgap-dev'
    TARGET_GROUP_NAME = 'TargetGroupPortal'  # consider better name?

    STACK_NAME_TOKEN = "ecs"
    STACK_TITLE_TOKEN = "ECS"
    SHARING = 'env'

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
        # Adds AppConfig Stack Parameter -- used to ImportValue the Falcon CID secret ARN for the
        # CrowdStrike sidecar (unused when crowdstrike.enabled is false). cli.py already supplies this
        # override for ECS stacks; declaring it here keeps template and provision inputs in sync.
        template.add_parameter(Parameter(
            self.APPCONFIG_EXPORTS.reference_param_key,
            Description='Name of appconfig stack for the CrowdStrike Falcon CID secret ARN ImportValue',
            Type='String',
        ))

        # ECS Params
        template.add_parameter(self.ecs_web_worker_port())
        # template.add_parameter(self.ecs_lb_certificate())  # TODO must be provisioned

        # ECS
        template.add_resource(self.ecs_cluster())

        # ECS Tasks/Services
        template.add_resource(self.ecs_portal_task())
        portal = self.ecs_portal_service()
        template.add_resource(portal)
        template.add_resource(self.ecs_indexer_task())
        template.add_resource(self.ecs_indexer_service())
        template.add_resource(self.ecs_ingester_task())
        template.add_resource(self.ecs_ingester_service())
        template.add_resource(self.ecs_deployment_task(initial=True))
        template.add_resource(self.ecs_deployment_task())

        # Add load balancer for portal
        template.add_resource(self.ecs_lb_security_group())
        template.add_resource(self.ecs_container_security_group())
        target_group = self.ecs_lbv2_target_group(name=self.TARGET_GROUP_NAME)
        template.add_resource(target_group)
        for listener in self.ecs_lb_listeners(target_group):
            template.add_resource(listener)
        template.add_resource(self.ecs_application_load_balancer())

        # Add indexing Cloudwatch Alarms
        # These alarms are meant to trigger symmetric scaling actions in response to
        # sustained indexing load - the specifics of the autoscaling is left for
        # manual configuration by the orchestrator according to their needs
        template.add_resource(self.indexer_queue_empty_alarm())
        template.add_resource(self.indexer_queue_depth_alarm())

        # Add ingestion Cloudwatch Alarms
        template.add_resource(self.ingester_queue_empty_alarm())
        template.add_resource(self.ingester_queue_depth_alarm())

        # Add outputs
        template.add_output(self.output_application_url())
        return template

    def _awslogs_config(self, stream_prefix, log_group_export=None) -> LogConfiguration:
        """ Shared awslogs LogConfiguration for ECS container definitions (RED-4). All ECS/task
            variants used a byte-identical block differing only in the stream prefix and (for
            blue/green) the log-group export; this factors that out. """
        return LogConfiguration(
            LogDriver='awslogs',
            Options={
                'awslogs-group':
                    self.LOGGING_EXPORTS.import_value(log_group_export or C4LoggingExports.APPLICATION_LOG_GROUP),
                'awslogs-region': Ref(AWS_REGION),
                'awslogs-stream-prefix': stream_prefix,
            }
        )

    # --- CrowdStrike Falcon container sensor (sidecar) helpers -----------------------------------
    #
    # These are shared by every ECS task variant (portal/indexer/ingester/deployment, single-cluster
    # and blue/green, CGAP/Fourfront/SMaHT, and -- via inheritance -- the SRCE variants). They are a
    # no-op unless crowdstrike.enabled is true, so existing deployments are byte-identical.
    #
    # The demonstrated contract (from the captain's vendor task definition):
    #   * a non-essential 'falcon-container' sidecar prepares a shared 'crowdstrike-falcon-volume'
    #     (task-level Host volume) and receives the Falcon CID as a Secrets-Manager-injected env var;
    #   * the application container mounts that volume read-only, is wrapped by the CrowdStrike loader
    #     entrypoint, and dependsOn the sidecar completing successfully before it starts.

    def crowdstrike_enabled(self) -> bool:
        """ Whether the CrowdStrike Falcon sidecar should be attached to ECS tasks (crowdstrike.enabled). """
        return bool(ConfigManager.get_config_setting(Settings.CROWDSTRIKE_ENABLED, default=False))

    def crowdstrike_mount_path(self) -> str:
        return ConfigManager.get_config_setting(Settings.CROWDSTRIKE_MOUNT_PATH,
                                                self.DEFAULT_CROWDSTRIKE_MOUNT_PATH)

    @staticmethod
    def _parse_crowdstrike_entrypoint(value):
        """ Parse the loader entrypoint from a config value that may be a real list, a JSON/py-repr
            array string, or a comma-separated string (config values are stringified for the
            os.environ round-trip -- see the CLN-10 note in src/base.py). Returns a list of args. """
        if isinstance(value, list):
            return [str(s).strip() for s in value if str(s).strip()]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith('['):
                try:
                    return [str(s).strip() for s in json.loads(stripped)]
                except json.JSONDecodeError:
                    inner = stripped[1:-1]
                    return [s.strip().strip("'\"") for s in inner.split(',') if s.strip()]
            return [s.strip() for s in stripped.split(',') if s.strip()]
        return []

    def crowdstrike_entrypoint(self) -> list:
        """ The CrowdStrike loader entrypoint the application container is wrapped with. Required when
            crowdstrike.enabled is true (no default): a wrong/empty entrypoint would emit a task
            definition that validates but never runs the application, so we fail loudly at build time. """
        entrypoint = self._parse_crowdstrike_entrypoint(
            ConfigManager.get_config_setting(Settings.CROWDSTRIKE_ENTRYPOINT, default=None))
        if not entrypoint:
            raise RuntimeError(
                f"crowdstrike.enabled is true but {Settings.CROWDSTRIKE_ENTRYPOINT!r} is not set. Supply the "
                f"CrowdStrike loader entrypoint (JSON list or comma-separated) that wraps the application "
                f"container -- this is a vendor/image-specific value; see docs/source/crowdstrike.rst.")
        return entrypoint

    def _crowdstrike_volume(self) -> Volume:
        """ Task-level shared volume the sidecar populates and the app mounts read-only. Host volume
            with an empty host (ephemeral, task-scoped) exactly as in the vendor example. """
        return Volume(Name=self.CROWDSTRIKE_VOLUME_NAME, Host=Host())

    def _falcon_sidecar_container(self, stream_prefix, log_group_export=None) -> ContainerDefinition:
        """ The non-essential Falcon sensor sidecar. Pulls the falcon-sensor image from ECR, mounts
            the shared volume read-write to prepare it, gets the Falcon CID injected from Secrets
            Manager (via the appconfig-owned export ARN), and logs like every other container. """
        sensor_tag = ConfigManager.get_config_setting(
            Settings.CROWDSTRIKE_SENSOR_IMAGE_TAG, self.DEFAULT_FALCON_SENSOR_IMAGE_TAG)
        backend = ConfigManager.get_config_setting(Settings.CROWDSTRIKE_BACKEND, self.DEFAULT_CROWDSTRIKE_BACKEND)
        return ContainerDefinition(
            Name=self.FALCON_SIDECAR_CONTAINER_NAME,
            Essential=False,
            Image=Join('', [
                self.ECR_EXPORTS.import_value(C4ECRExports.FALCON_SENSOR_URL),
                ':',
                sensor_tag,
            ]),
            Environment=[Environment(Name=self.FALCON_BACKEND_ENV_NAME, Value=backend)],
            Secrets=[Secret(
                Name=self.FALCON_CID_SECRET_ENV_NAME,
                ValueFrom=self.APPCONFIG_EXPORTS.import_value(C4AppConfigExports.EXPORT_FALCON_CID),
            )],
            MountPoints=[MountPoint(
                SourceVolume=self.CROWDSTRIKE_VOLUME_NAME,
                ContainerPath=self.crowdstrike_mount_path(),
                ReadOnly=False,  # the sidecar writes the sensor rootfs here
            )],
            LogConfiguration=self._awslogs_config(stream_prefix, log_group_export),
        )

    def _crowdstrike_task_kwargs(self, app_container: ContainerDefinition,
                                 sidecar_stream_prefix, log_group_export=None) -> dict:
        """ Return the TaskDefinition ContainerDefinitions/Volumes kwargs for an application task,
            wrapping it with the CrowdStrike sidecar when enabled and otherwise leaving it exactly
            as before (single container, no Volumes key). Mutates app_container in place to add the
            read-only mount, loader entrypoint, and dependsOn ordering.

            :param app_container: the primary application ContainerDefinition (already built)
            :param sidecar_stream_prefix: awslogs stream prefix for the sidecar's own log stream
            :param log_group_export: log-group export to use (threaded through for blue/green)
        """
        if not self.crowdstrike_enabled():
            return {'ContainerDefinitions': [app_container]}
        mount_path = self.crowdstrike_mount_path()
        existing_mounts = getattr(app_container, 'MountPoints', None) or []
        app_container.MountPoints = existing_mounts + [MountPoint(
            SourceVolume=self.CROWDSTRIKE_VOLUME_NAME,
            ContainerPath=mount_path,
            ReadOnly=True,  # the application only reads the sensor rootfs
        )]
        app_container.EntryPoint = self.crowdstrike_entrypoint()
        app_container.DependsOn = [ContainerDependency(
            ContainerName=self.FALCON_SIDECAR_CONTAINER_NAME,
            Condition=self.FALCON_SIDECAR_DEPENDS_CONDITION,
        )]
        return {
            'ContainerDefinitions': [
                app_container,
                self._falcon_sidecar_container(sidecar_stream_prefix, log_group_export),
            ],
            'Volumes': [self._crowdstrike_volume()],
        }

    def ecs_cluster(self) -> Cluster:
        """ Creates an ECS cluster for use with this portal deployment. """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Cluster(
            # Fallback, but should always be set
            f'{ConfigManager.get_config_setting(Settings.APP_KIND)}DockerClusterFor{camelize(env_name)}',
            # dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME, 'CGAPDockerCluster'))
            CapacityProviders=['FARGATE', 'FARGATE_SPOT'],
            Tags=self.tags.cost_tag_obj()  # XXX: bug in troposphere - does not take tags array
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
        """
        Parameter for the portal port - by default 8000 (requires change to nginx config on cgap-portal to modify)
        """
        return Parameter(
            'WebWorkerPort',
            Description='Web worker container exposed port',
            Type='Number',
            Default=8000,  # port exposed by portal container
        )

    def ecs_container_security_group(self) -> SecurityGroup:
        """ Security group for the container runtime. """
        logical_id = self.name.logical_id('ContainerSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupDescription='Container Security Group.',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            SecurityGroupIngress=[
                # HTTP from web public subnets
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=Ref(self.ecs_web_worker_port()),
                    ToPort=Ref(self.ecs_web_worker_port()),
                    CidrIp=C4Network.CIDR_BLOCK,
                )
            ],
            Tags=self.tags.cost_tag_array()
        )

    def ecs_lb_security_group(self) -> SecurityGroup:
        """ Security group for the load balancer, allowing traffic on ports 80/443.
            TODO: configure for HTTPS.
        """
        logical_id = self.name.logical_id('LBSecurityGroup')
        return SecurityGroup(
            logical_id,
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

    # Modern TLS policy (TLS 1.2/1.3) for the HTTPS listener.
    LB_SSL_POLICY = 'ELBSecurityPolicy-TLS13-1-2-2021-06'

    def lb_certificate_arn(self):
        """ ACM certificate ARN for the portal ALB, from config (ecs.lb_certificate_arn). When
            present, HTTPS is enabled on the ALB (SEC-5). """
        return ConfigManager.get_config_setting(Settings.ECS_LB_CERTIFICATE_ARN, default=None)

    def ecs_forwarding_listener_id(self, deployment_type=''):
        """Wait for the listener that associates the service's target group with the ALB."""
        prefix = 'LBHTTPSListener' if self.lb_certificate_arn() else 'LBListener'
        return self.name.logical_id(f'{prefix}{deployment_type}')

    def ecs_lb_listeners(self, target_group: elbv2.TargetGroup, deployment_type='', lb_ref=None) -> list:
        """ Listeners for the portal ALB.

            When an ACM certificate is configured (ecs.lb_certificate_arn), serve HTTPS on 443
            (forwarding to the portal target group with a modern SslPolicy) and redirect HTTP:80 to
            HTTPS:443. When no certificate is configured, fall back to a plain HTTP:80 forward
            listener (unchanged legacy behavior). (SEC-5)
        """
        cert_arn = self.lb_certificate_arn()
        lb_arn = lb_ref if lb_ref is not None else Ref(self.ecs_application_load_balancer())
        forward = [elbv2.Action(Type='forward', TargetGroupArn=Ref(target_group))]
        if not cert_arn:
            return [elbv2.Listener(
                self.name.logical_id(f'LBListener{deployment_type}'),
                Port=80, Protocol='HTTP',
                LoadBalancerArn=lb_arn,
                DefaultActions=forward,
            )]
        https_listener = elbv2.Listener(
            self.name.logical_id(f'LBHTTPSListener{deployment_type}'),
            Port=443, Protocol='HTTPS',
            LoadBalancerArn=lb_arn,
            SslPolicy=self.LB_SSL_POLICY,
            Certificates=[elbv2.Certificate(CertificateArn=cert_arn)],
            DefaultActions=forward,
        )
        http_redirect = elbv2.Listener(
            self.name.logical_id(f'LBListener{deployment_type}'),
            Port=80, Protocol='HTTP',
            LoadBalancerArn=lb_arn,
            DefaultActions=[elbv2.Action(
                Type='redirect',
                RedirectConfig=elbv2.RedirectConfig(
                    Protocol='HTTPS', Port='443', StatusCode='HTTP_301',
                ),
            )],
        )
        return [https_listener, http_redirect]

    @staticmethod
    def ecs_target_group_stickiness_options():
        """ Configure the LB such that a session cookie is used to map user sessions to specific
            worker nodes on a 1 hour rotating basis.
        """
        return [
            elbv2.TargetGroupAttribute(Key='stickiness.enabled', Value='true'),
            elbv2.TargetGroupAttribute(Key='stickiness.lb_cookie.duration_seconds', Value='3600'),
        ]

    def ecs_application_load_balancer(self, deployment_type='') -> elbv2.LoadBalancer:
        """ Application load balancer for the portal ECS Task.
            Allows one to pass a "deployment_type", allowing blue/green configuration
            In this case deployment_type == '', 'blue' or 'green'
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        if deployment_type:
            env_name = env_name + deployment_type
        logical_id = self.name.logical_id(f'{deployment_type}LoadBalancer')
        return elbv2.LoadBalancer(
            logical_id,
            IpAddressType='ipv4',
            Name=env_name,  # was logical_id
            Scheme='internet-facing',
            SecurityGroups=[
                Ref(self.ecs_lb_security_group())
            ],
            Subnets=[self.NETWORK_EXPORTS.import_value(subnet_key)
                    for subnet_key in self.NETWORK_EXPORTS.PUBLIC_SUBNETS],
            LoadBalancerAttributes=self._alb_access_log_attributes(),
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type='application',
        )

    @staticmethod
    def _alb_access_log_attributes() -> list:
        """ ALB access-log LoadBalancerAttributes (SEC-9). Off unless alb.access_logs_bucket names
            a pre-existing, ELB-writable S3 bucket; then access logs are written there (optionally
            under alb.access_logs_prefix). Returns [] when unset so existing deploys are unchanged. """
        bucket = ConfigManager.get_config_setting(Settings.ALB_ACCESS_LOGS_BUCKET, default=None)
        if not bucket:
            return []
        attrs = [
            elbv2.LoadBalancerAttributes(Key='access_logs.s3.enabled', Value='true'),
            elbv2.LoadBalancerAttributes(Key='access_logs.s3.bucket', Value=bucket),
        ]
        prefix = ConfigManager.get_config_setting(Settings.ALB_ACCESS_LOGS_PREFIX, default=None)
        if prefix:
            attrs.append(elbv2.LoadBalancerAttributes(Key='access_logs.s3.prefix', Value=prefix))
        return attrs

    def output_application_url(self, env=None) -> Output:
        """ Outputs URL to access portal. Emits https:// when an ACM cert is configured (SEC-5). """
        env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
        scheme = 'https://' if self.lb_certificate_arn() else 'http://'
        return Output(
            C4ECSApplicationExports.output_application_url_key(env),
            Description=f'URL of {ConfigManager.get_config_setting(Settings.APP_KIND)}-Portal.',
            Value=Join('', [scheme, GetAtt(self.ecs_application_load_balancer(), 'DNSName')])
        )

    def _lbv2_target_group(self, name):
        logical_id = self.name.logical_id(name)
        return elbv2.TargetGroup(
            logical_id,
            HealthCheckIntervalSeconds=60,
            HealthCheckPath='/health?format=json',
            HealthCheckProtocol='HTTP',
            HealthCheckTimeoutSeconds=10,
            Matcher=elbv2.Matcher(HttpCode='200'),
            Name=name,
            Port=Ref(self.ecs_web_worker_port()),
            TargetType='ip',
            TargetGroupAttributes=self.ecs_target_group_stickiness_options(),
            Protocol='HTTP',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array()
        )

    def ecs_lbv2_target_group(self, name=TARGET_GROUP_NAME) -> elbv2.TargetGroup:
        """ Creates LBv2 target group (intended for use with portal Service). """
        return self._lbv2_target_group(name)

    def ecs_portal_task(self, cpu='4096', mem='8192', identity=None) -> TaskDefinition:   # XXX: refactor
        """ Defines the portal Task (serve HTTP requests).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task
            :param mem: Memory amount for this task
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
        """
        return TaskDefinition(
            f'{ConfigManager.get_config_setting(Settings.APP_KIND)}portal',
            RequiresCompatibilities=['FARGATE'],
            Cpu=ConfigManager.get_config_setting(Settings.ECS_WSGI_CPU, cpu),
            Memory=ConfigManager.get_config_setting(Settings.ECS_WSGI_MEMORY, mem),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            **self._crowdstrike_task_kwargs(
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
                    LogConfiguration=self._awslogs_config(
                        f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-portal'),
                    Environment=[
                        # VERY IMPORTANT - this environment variable determines which identity in the secrets manager
                        # to use. If this secret does not exist, things will not start up correctly - this is ok in
                        # the short term, but shortly after orchestration the secret value should be set.
                        # Note this applies to all other tasks as well.
                        #
                        # NOTE ALSO - if the missing parts of the secrets are not filled out manually, the system will
                        # not come online. There's info on how to fill them out in docs/deploy-new-account.rst
                        Environment(
                            Name='IDENTITY',
                            Value=(identity
                                   or ConfigManager.get_config_setting(Settings.IDENTITY,
                                                                       self.LEGACY_DEFAULT_IDENTITY)),
                        ),
                        Environment(
                            Name='application_type',
                            Value=C4ECSApplicationTypes.PORTAL
                        ),
                    ]
                ),
                sidecar_stream_prefix=f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-portal-falcon',
            ),
            Tags=self.tags.cost_tag_obj(),
        )

    def ecs_portal_service(self, concurrency=2) -> Service:
        """ Defines the portal service (manages portal Tasks)
            Note dependencies: https://stackoverflow.com/questions/53971873/the-target-group-does-not-have-an-associated-load-balancer

            Defined by the ECR Image tag 'latest'.

            :param concurrency: # of concurrent tasks to run - since this setup is intended for use with
                                production, this value is 8, approximately matching our current resources.
        """  # noQA - ignore line length issues
        return Service(
            f"{ConfigManager.get_config_setting(Settings.APP_KIND)}portalService",
            Cluster=Ref(self.ecs_cluster()),
            DependsOn=[self.ecs_forwarding_listener_id()],
            DesiredCount=ConfigManager.get_config_setting(Settings.ECS_WSGI_COUNT, concurrency),
            LoadBalancers=[
                LoadBalancer(
                    ContainerName='portal',  # this must match Name in TaskDefinition (ContainerDefinition)
                    ContainerPort=Ref(self.ecs_web_worker_port()),
                    TargetGroupArn=Ref(self.ecs_lbv2_target_group(name=self.TARGET_GROUP_NAME)))
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
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in self.NETWORK_EXPORTS.PRIVATE_SUBNETS
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    DEFAULT_INDEXER_CPU = '256'
    DEFAULT_INDEXER_MEMORY = '512'

    def ecs_indexer_task(self, cpu=None, memory=None, identity=None) -> TaskDefinition:
        """ Defines the Indexer task (indexer app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task
            :param memory: Memory amount for this task
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
        """
        return TaskDefinition(
            f'{ConfigManager.get_config_setting(Settings.APP_KIND)}Indexer',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpu or ConfigManager.get_config_setting(Settings.ECS_INDEXER_CPU, self.DEFAULT_INDEXER_CPU),
            Memory=memory or ConfigManager.get_config_setting(Settings.ECS_INDEXER_MEMORY, self.DEFAULT_INDEXER_MEMORY),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            **self._crowdstrike_task_kwargs(
                ContainerDefinition(
                    Name='Indexer',
                    Essential=True,
                    Image=Join('', [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG,
                    ]),
                    LogConfiguration=self._awslogs_config(
                        f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-indexer'),
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
                            Value=C4ECSApplicationTypes.INDEXER
                        ),
                    ]
                ),
                sidecar_stream_prefix=f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-indexer-falcon',
            ),
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
            f"{ConfigManager.get_config_setting(Settings.APP_KIND)}IndexerService",
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
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in self.NETWORK_EXPORTS.PRIVATE_SUBNETS
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )

    @staticmethod
    def indexer_queue_depth_alarm(depth=1000, deployment_type='') -> Alarm:
        """ Creates a Cloudwatch alarm for Secondary queue depth.
            Checks the secondary queue to see if it is backlogged.
            Allows passing a deployment_type (for use with blue/green).
            In this case deployment_type == '', 'blue' or 'green'
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        queue_name = (f'{env_name}-{deployment_type}-secondary-indexer-queue'
                      if deployment_type else
                      f'{env_name}-secondary-indexer-queue')
        return Alarm(
            f'IndexingQueueDepthAlarm{deployment_type}',
            AlarmDescription='Alarm if total queue depth exceeds %s' % depth,
            Namespace='AWS/SQS',
            MetricName='ApproximateNumberOfMessagesVisible',
            Dimensions=[
                MetricDimension(
                    Name='QueueName',
                    Value=queue_name,
                )
            ],
            Statistic='Maximum',
            Period='300',
            EvaluationPeriods='1',
            Threshold=depth,
            ComparisonOperator='GreaterThanThreshold',
        )

    @staticmethod
    def indexer_queue_empty_alarm(deployment_type='') -> Alarm:
        """ Creates a Cloudwatch alarm for when the Secondary queue is empty.
            Checks the secondary queue to see if it is empty, if detected scale down.
            Allows passing a deployment_type (for use with blue/green).
            In this case deployment_type == '', 'blue' or 'green'
        """
        return Alarm(
            f'IndexingQueueEmptyAlarm{deployment_type}',
            AlarmDescription='Alarm when queue depth reaches 0',
            Namespace='AWS/SQS',
            MetricName='ApproximateNumberOfMessagesVisible',
            Dimensions=[
                MetricDimension(
                    Name='QueueName',
                    Value=ConfigManager.get_config_setting(Settings.ENV_NAME) +
                    f'-{deployment_type}-secondary-indexer-queue'),
            ],
            Statistic='Maximum',
            Period='300',
            EvaluationPeriods='1',
            Threshold=0,
            ComparisonOperator='LessThanOrEqualToThreshold',
        )

    DEFAULT_INGESTER_CPU = '512'
    DEFAULT_INGESTER_MEMORY = '1024'

    def ecs_ingester_task(self, cpu=None, memory=None, identity=None) -> TaskDefinition:
        """ Defines the Ingester task (ingester app).
            See: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ecs-taskdefinition.html

            :param cpu: CPU value to assign to this task, default 256 (play with this value)
            :param memory: Memory amount for this task, default to 512 (play with this value)
            :param identity: name of secret containing the identity information for this environment
                             (defaults to value of environment variable IDENTITY,
                             or to C4ECSApplication.LEGACY_DEFAULT_IDENTITY if that is empty or undefined).
        """
        return TaskDefinition(
            f'{ConfigManager.get_config_setting(Settings.APP_KIND)}Ingester',
            RequiresCompatibilities=['FARGATE'],
            Cpu=cpu or ConfigManager.get_config_setting(Settings.ECS_INGESTER_CPU, self.DEFAULT_INGESTER_CPU),
            Memory=memory or ConfigManager.get_config_setting(Settings.ECS_INGESTER_MEMORY,
                                                              self.DEFAULT_INGESTER_MEMORY),
            TaskRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            ExecutionRoleArn=self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE),
            NetworkMode='awsvpc',  # required for Fargate
            **self._crowdstrike_task_kwargs(
                ContainerDefinition(
                    Name='Ingester',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG
                    ]),
                    LogConfiguration=self._awslogs_config(
                        f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-ingester'),
                    Environment=[
                        Environment(
                            Name='IDENTITY',
                            Value=(identity
                                   or ConfigManager.get_config_setting(Settings.IDENTITY,
                                                                       self.LEGACY_DEFAULT_IDENTITY)),
                        ),
                        Environment(
                            Name='application_type',
                            Value=C4ECSApplicationTypes.INGESTER
                        ),
                    ]
                ),
                sidecar_stream_prefix=f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-ingester-falcon',
            ),
            Tags=self.tags.cost_tag_obj()
        )

    def ecs_ingester_service(self) -> Service:
        """ Defines the Ingester service (manages Ingestion Tasks)

            Defined by the ECR Image tag 'latest-ingester'
            TODO SQS Trigger?
        """
        return Service(
            f"{ConfigManager.get_config_setting(Settings.APP_KIND)}IngesterService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=ConfigManager.get_config_setting(Settings.ECS_INGESTER_COUNT, 1),
            TaskDefinition=Ref(self.ecs_ingester_task()),
            SchedulingStrategy=SCHEDULING_STRATEGY_REPLICA,
            NetworkConfiguration=NetworkConfiguration(
                AwsvpcConfiguration=AwsvpcConfiguration(
                    Subnets=[
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in self.NETWORK_EXPORTS.PRIVATE_SUBNETS
                    ],
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
            Tags=self.tags.cost_tag_obj()
        )

    @staticmethod
    def ingester_queue_depth_alarm(depth=2) -> Alarm:
        """ Creates a Cloudwatch alarm for Indexer + Secondary queue depth.
            Checks the secondary queue to see if it is backlogged.
        """
        return Alarm(
            'IngesterQueueDepthAlarm',
            AlarmDescription='Alarm if total queue depth exceeds %s' % depth,
            Namespace='AWS/SQS',
            MetricName='ApproximateNumberOfMessagesVisible',
            Dimensions=[
                MetricDimension(Name='QueueName',
                                Value=ConfigManager.get_config_setting(Settings.ENV_NAME) + '-ingestion-queue'),
            ],
            Statistic='Maximum',
            Period='300',
            EvaluationPeriods='1',
            Threshold=depth,
            ComparisonOperator='GreaterThanThreshold',
        )

    @staticmethod
    def ingester_queue_empty_alarm() -> Alarm:
        """ Creates a Cloudwatch alarm for when Indexer + Secondary queue are empty.
            Checks the secondary queue to see if it is empty, if detected scale down.
        """
        return Alarm(
            'IngesterQueueEmptyAlarm',
            AlarmDescription='Alarm when queue depth reaches 0',
            Namespace='AWS/SQS',
            MetricName='ApproximateNumberOfMessagesVisible',
            Dimensions=[
                MetricDimension(Name='QueueName',
                                Value=ConfigManager.get_config_setting(Settings.ENV_NAME) + '-ingestion-queue'),
            ],
            Statistic='Maximum',
            Period='300',
            EvaluationPeriods='1',
            Threshold=0,
            ComparisonOperator='LessThanOrEqualToThreshold',
        )

    DEFAULT_INITIAL_DEPLOYMENT_CPU = '1024'
    DEFAULT_INITIAL_DEPLOYMENT_MEMORY = '2048'

    DEFAULT_DEPLOYMENT_CPU = '1024'
    DEFAULT_DEPLOYMENT_MEMORY = '2048'

    def ecs_deployment_task(self, cpu=None, memory=None, identity=None, initial=False) -> TaskDefinition:
        """ Defines the Deployment task (run deployment action).
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
            f'{ConfigManager.get_config_setting(Settings.APP_KIND)}InitialDeployment' if initial else f'{ConfigManager.get_config_setting(Settings.APP_KIND)}Deployment',
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
            **self._crowdstrike_task_kwargs(
                ContainerDefinition(
                    Name='DeploymentAction',
                    Essential=True,
                    Image=Join("", [
                        self.ECR_EXPORTS.import_value(C4ECRExports.PORTAL_REPO_URL),
                        ':',
                        self.IMAGE_TAG,
                    ]),
                    LogConfiguration=self._awslogs_config(
                        f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-initial-deployment' if initial
                        else f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-deployment'),
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
                            Value=C4ECSApplicationTypes.DEPLOYMENT
                        ),
                    ]
                ),
                sidecar_stream_prefix=(
                    f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-initial-deployment-falcon' if initial
                    else f'{ConfigManager.get_config_setting(Settings.APP_KIND)}-deployment-falcon'),
            ),
            Tags=self.tags.cost_tag_obj()
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
            f"{ConfigManager.get_config_setting(Settings.APP_KIND)}DeploymentService",
            Cluster=Ref(self.ecs_cluster()),
            DesiredCount=0,  # Explicitly triggered
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
                    Subnets=[
                        self.NETWORK_EXPORTS.import_value(subnet_key)
                        for subnet_key in self.NETWORK_EXPORTS.PRIVATE_SUBNETS
                    ],
                    SecurityGroups=[Ref(self.ecs_container_security_group())],
                )
            ),
            Tags=self.tags.cost_tag_obj()
        )
