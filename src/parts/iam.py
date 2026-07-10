from awacs.aws import PolicyDocument, Statement, Action, Principal, AWSPrincipal
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from troposphere import Region, AccountId, Template, Ref, Output, Join
from troposphere.iam import Role, InstanceProfile, Policy, User, AccessKey
from ..base import ConfigManager
from ..constants import C4IAMBase, Settings
from ..part import C4Part
from ..exports import C4Exports, exportify
from ..names import Names


class C4IAMExports(C4Exports):
    """ Defines exports for IAM, consisting of:
            * assumed IAM role for ECS container
            * corresponding instance profile
    """
    ECS_ASSUMED_IAM_ROLE = exportify('ECSAssumedIAMRole')  # was 'ExportECSAssumedIAMRole'
    ECS_INSTANCE_PROFILE = exportify('ECSInstanceProfile')  # was 'ExportECSInstanceProfile'
    AUTOSCALING_IAM_ROLE = exportify('ECSAutoscalingIAMRole')  # was 'ExportECSAutoscalingIAMRole'
    DEV_IAM_ROLE = exportify('ECSDevUserRole')
    S3_IAM_USER = exportify('ECSS3IAMUser')  # was 'ExportECSS3IAMUser'

    def __init__(self):
        parameter = 'IAMStackNameParameter'
        super().__init__(parameter)


class C4IAM(C4IAMBase, C4Part):
    """ Contains IAM Role configuration for CGAP/FF.
        Both apps have the same permission sets needed (for now) so the roles are used interchangably.
        If this changes, feel free to extend this class and override as needed.
        Right now, there is only one important IAM Role to configure.
        That is the assumed IAM role assigned to ECS.
    """
    ROLE_NAME = ConfigManager.app_case(if_cgap='CGAPECSRole',
                                       if_ff='FFECSRole',
                                       if_smaht='SMaHTECSRole')
    DEV_ROLE = ConfigManager.app_case(if_cgap='CGAPDevRole',
                                      if_ff='FFDevRole',
                                      if_smaht='SMaHTDevRole')
    INSTANCE_PROFILE_NAME = ConfigManager.app_case(if_cgap='CGAPECSInstanceProfile',
                                                   if_ff='FFECSInstanceProfile',
                                                   if_smaht='SMaHTInstanceProfile')
    AUTOSCALING_ROLE_NAME = ConfigManager.app_case(if_cgap='CGAPECSAutoscalingRole',
                                                   if_ff='FFECSAutoscalingRole',
                                                   if_smaht='SMaHTAutoscalingRole')
    EXPORTS = C4IAMExports()
    # dmichaels/2022-06-22: Factored out into C4IAMBase in constants.py
    # SHARING = 'ecosystem'

    def build_template(self, template: Template) -> Template:
        """ Builds current IAM template, currently just the ECS assumed IAM role
            and instance profile.
        """
        iam_role = self.ecs_assumed_iam_role()
        template.add_resource(iam_role)
        flowlog_role = self.vcp_flowlog_role()
        template.add_resource(flowlog_role)  # no need to export, only used for logs
        dev_iam_role = self.dev_user_role()
        template.add_resource(dev_iam_role)
        instance_profile = self.ecs_instance_profile()
        template.add_resource(instance_profile)
        autoscaling_iam_role = self.ecs_autoscaling_role()
        template.add_resource(autoscaling_iam_role)
        s3_iam_user = self.ecs_s3_iam_user()
        template.add_resource(s3_iam_user)
        # s3_iam_user_access_key = self.ecs_s3_iam_user_access_key(s3_iam_user)
        # template.add_resource(s3_iam_user_access_key)  # TODO: properly extract and pass this key

        # add outputs
        template.add_output(self.output_assumed_iam_role_or_user(iam_role,
                                                                 export_name=C4IAMExports.ECS_ASSUMED_IAM_ROLE))
        template.add_output(self.output_assumed_iam_role_or_user(autoscaling_iam_role,
                                                                 export_name=C4IAMExports.AUTOSCALING_IAM_ROLE))
        template.add_output(self.output_assumed_iam_role_or_user(s3_iam_user,
                                                                 export_name=C4IAMExports.S3_IAM_USER))
        template.add_output(self.output_assumed_iam_role_or_user(dev_iam_role,
                                                                 export_name=C4IAMExports.DEV_IAM_ROLE))
        template.add_output(self.output_instance_profile(instance_profile))
        return template

    @staticmethod
    def build_sqs_arn(prefix):
        return Join(
            ':', ['arn', 'aws', 'sqs', Region, AccountId, prefix]
        )

    @staticmethod
    def builds_secret_manager_arn(secret_name):
        # Secrets Manager ARN format: arn:aws:secretsmanager:region:account:secret:name-suffix
        # AWS appends a random 6-char suffix (-xxxxxx); a trailing wildcard on the name covers this.
        return Join(
            ':', ['arn', 'aws', 'secretsmanager', Region, AccountId,
                  Join('', ['secret:', secret_name])]
        )

    @staticmethod
    def build_elasticsearch_arn(domain_name):
        return Join(
            ':', ['arn', 'aws', 'es', Region, AccountId, 'domain/' + domain_name]
        )

    @staticmethod
    def build_logging_arn(log_group_name):
        return Join(
            ':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group', log_group_name]
        )

    def ecs_sqs_policy(self, prefix=None) -> Policy:
        """ Grants ECS access to SQS queues. Scoped to the minimum actions needed for
            portal indexing/ingestion and to the env's queues, which are named
            '{env_name}-<suffix>' (see datastore.build_sqs_instance). 'sqs:ListQueues' is an
            account-level action that does not support resource-level restriction, so it lives
            in its own statement scoped to '*'.
        """
        if prefix is None:
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            prefix = f'{env_name}-*'
        return Policy(
            PolicyName='ECSSQSAccessPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=[
                            'sqs:SendMessage',
                            'sqs:ReceiveMessage',
                            'sqs:DeleteMessage',
                            'sqs:GetQueueAttributes',
                            'sqs:GetQueueUrl',
                            'sqs:ChangeMessageVisibility',
                        ],
                        Resource=[self.build_sqs_arn(prefix)],
                    ),
                    dict(
                        Effect='Allow',
                        Action=['sqs:ListQueues'],
                        Resource=['*'],
                    ),
                ]
            )
        )

    def ecs_es_policy(self, domain_name=None) -> Policy:
        """ Grants ECS access to OpenSearch/Elasticsearch. HTTP data-plane actions are scoped to
            the env's domain, which is named 'os-{env_name}' (see datastore.opensearch_instance).
            The Describe*/ListDomainNames actions are account-level and do not support
            resource-level restriction, so they live in their own '*'-scoped statement.
        """
        if domain_name is None:
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            domain_name = f'os-{env_name}*'
        return Policy(
            PolicyName='ECSESAccessPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=[
                            'es:ESHttpGet',
                            'es:ESHttpPost',
                            'es:ESHttpPut',
                            'es:ESHttpDelete',
                            'es:ESHttpHead',
                            'es:ESHttpPatch',
                        ],
                        Resource=[self.build_elasticsearch_arn(domain_name)],
                    ),
                    dict(
                        Effect='Allow',
                        Action=[
                            'es:DescribeElasticsearchDomains',
                            'es:DescribeDomain',
                            'es:ListDomainNames',
                        ],
                        Resource=['*'],
                    ),
                ],
            )
        )

    def ecs_secret_manager_policy(self) -> Policy:
        """ Provides ECS access to secrets. Scoped to the secrets created by this infrastructure:
            'C4AppConfig*' (the GAC, Foursight config, and Falcon credential stubs from the
            appconfig stack) and 'C4Datastore*' (the RDS master-credential secret). AWS appends a
            random 6-char suffix to secret ARNs, which the trailing wildcard also covers.
        """
        return Policy(
            PolicyName='ECSSecretManagerPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'secretsmanager:GetSecretValue',
                        'secretsmanager:DescribeSecret',
                        'secretsmanager:ListSecretVersionIds',
                    ],
                    Resource=[
                        self.builds_secret_manager_arn('C4AppConfig*'),
                        self.builds_secret_manager_arn('C4Datastore*'),
                    ],
                )],
            )
        )

    @staticmethod
    def ecs_assume_role_policy() -> Policy:
        """ Allow ECS to assume this role. """
        return Policy(
            PolicyName='ECSAssumeIAMRolePolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'sts:AssumeRole',
                    ],
                    Principal=dict(Service=['ecs.amazonaws.com']),
                )],
            )
        )

    @staticmethod
    def ecs_access_policy() -> Policy:
        """ Give ECS access to manage its own services and interact with load balancers.
            Resource must be '*' — most ECS and ELB Describe actions do not support
            resource-level restrictions.
        """
        return Policy(
            PolicyName='ECSManagementPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect="Allow",
                    Action=[
                        'ecs:DescribeServices',
                        'ecs:DescribeTaskDefinition',
                        'ecs:DescribeTasks',
                        'ecs:DescribeClusters',
                        'ecs:ListTasks',
                        'ecs:ListServices',
                        'ecs:ListClusters',
                        'ecs:RunTask',
                        'ecs:StopTask',
                        'ecs:UpdateService',
                        'ecs:RegisterTaskDefinition',
                        'ecs:DeregisterTaskDefinition',
                        'ecs:CreateService',
                        'ecs:DeleteService',
                        'ecs:TagResource',
                        'elasticloadbalancing:DescribeLoadBalancers',
                        'elasticloadbalancing:DescribeTargetGroups',
                        'elasticloadbalancing:DescribeTargetHealth',
                        'elasticloadbalancing:DescribeListeners',
                        'elasticloadbalancing:DescribeRules',
                        'elasticloadbalancing:RegisterTargets',
                        'elasticloadbalancing:DeregisterTargets',
                    ],
                    Resource=['*'],
                )],
            ),
        )

    @staticmethod
    def ecs_log_policy() -> Policy:
        """ Grants ECS container the ability to log to CloudWatch. Scoped to log groups
            and streams with the 'c4-' naming prefix.
        """
        log_group_arn = Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group:c4-*'])
        log_stream_arn = Join(':', ['arn', 'aws', 'logs', Region, AccountId,
                                    'log-group:c4-*:log-stream:*'])
        return Policy(
            PolicyName='ECSLoggingPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'logs:CreateLogGroup',
                        'logs:CreateLogStream',
                        'logs:PutLogEvents',
                    ],
                    Resource=[log_group_arn, log_stream_arn],
                )]
            )
        )

    def ecs_ecr_policy(self) -> Policy:
        """ Policy allowing ECS to pull ECR images. GetAuthorizationToken is an account-level
            call that requires Resource '*'; image pull actions are scoped to the exact set of
            repositories the ECR stack creates: the env portal repo (named after ENV_NAME) plus
            the fixed pipeline/sidecar repos enumerated in ecr.ECR_REPO_NAMES.
        """
        # Lazy import avoids a circular dependency: ecr.py imports C4IAMExports from this module.
        from .ecr import ECR_REPO_NAMES
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        repo_names = [env_name] + ECR_REPO_NAMES
        repo_arns = [Join(':', ['arn', 'aws', 'ecr', Region, AccountId, f'repository/{name}'])
                     for name in repo_names]
        return Policy(
            PolicyName='ECSECRPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=[GetAuthorizationToken],
                        Resource=['*'],
                    ),
                    dict(
                        Effect='Allow',
                        Action=[
                            GetDownloadUrlForLayer,
                            BatchGetImage,
                            BatchCheckLayerAvailability,
                        ],
                        Resource=repo_arns,
                    ),
                ],
            ),
        )

    @staticmethod
    def ecs_web_service_policy() -> Policy:
        """ Policy needed by load balancer to allow target group registration.

            NOTE: ec2:AuthorizeSecurityGroupIngress was intentionally dropped (SEC-7). Nothing in
            the portal should mutate security groups at runtime; leaving it granted let any portal
            task open any security group in the account. The remaining Describe* actions do not
            support resource-level restriction, so they stay scoped to '*'.
        """
        return Policy(
            PolicyName='ECSWebServicePolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'elasticloadbalancing:Describe*',
                        'elasticloadbalancing:DeregisterInstancesFromLoadBalancer',
                        'elasticloadbalancing:RegisterInstancesWithLoadBalancer',
                        'ec2:Describe*',
                    ],
                    Resource=['*'],
                )],
            ),
        )

    @staticmethod
    def ecs_cfn_policy() -> Policy:
        """ Gives access to CloudFormation stack APIs so application services can read stack outputs.
            ListStacks is an account-level action (requires '*'); DescribeStacks is scoped to 'c4-*' stacks.

            Associated API: get_ecs_real_url, others within foursight
        """
        stack_arn = Join(':', ['arn', 'aws', 'cloudformation', Region, AccountId, 'stack/c4-*/*'])
        return Policy(
            PolicyName='ECSCfnPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=['cloudformation:ListStacks'],
                        Resource=['*'],
                    ),
                    dict(
                        Effect='Allow',
                        Action=['cloudformation:DescribeStacks'],
                        Resource=[stack_arn],
                    ),
                ],
            ),
        )

    def ecs_s3_policy(self) -> Policy:
        """ Gives s3 read/write access, scoped to this env's buckets. All buckets this
            infrastructure creates (application + foursight + the global env bucket) are named
            '{env_name}-<suffix>' (see datastore.build_s3_bucket), so scope to 'arn:aws:s3:::
            {env_name}-*' for ListBucket and '.../*' for the object actions rather than '*' (SEC-7).
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        bucket_arn = f'arn:aws:s3:::{env_name}-*'
        object_arn = f'arn:aws:s3:::{env_name}-*/*'
        return Policy(
            PolicyName='ECSS3Policy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=['s3:ListBucket'],
                        Resource=[bucket_arn],
                    ),
                    dict(
                        Effect='Allow',
                        Action=['s3:PutObject', 's3:GetObject', 's3:DeleteObject'],
                        Resource=[object_arn],
                    ),
                ],
            ),
        )

    @staticmethod
    def ecs_autoscaling_access_policy() -> Policy:
        """ Contains policies needed for the IAM role assumed by the autoscaling service. """
        return Policy(
            PolicyName='ECSPortalAutoscalingPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'ecs:DescribeServices',
                        'ecs:UpdateService',
                        'cloudwatch:PutMetricAlarm',
                        'cloudwatch:DescribeAlarms',
                        'cloudwatch:DeleteAlarms',
                    ],
                    Resource='*',  # XXX: constrain further?
                )],
            )
        )

    @staticmethod
    def ecs_s3_user_sts_policy() -> Policy:
        """ A policy allowing the GetFederationToken action, meant to be attached to the IAM
            user who federates access to S3.
        """
        return Policy(
            PolicyName='ECSSTSPolicyforS3Access',
            PolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": "sts:GetFederationToken",
                        "Resource": "*"
                    }
                ]
            }
        )

    def kms_policy(self) -> Policy:
        """ Defines a policy that gives permission access to a subset of actions on KMS.
            Needed for the S3Federator to generate URLs that enable server side encryption.

            Scoped to the S3-encrypt KMS key when its id is known via the s3.encrypt_key_id config
            setting (SEC-7). Falls back to '*' when the key id is not configured — this is the
            bootstrap case, since the IAM stack is deployed before the datastore stack that creates
            the key. Set s3.encrypt_key_id once the key exists to tighten this on the next update.
        """
        key_id = ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None)
        if key_id:
            resource = [Join(':', ['arn', 'aws', 'kms', Region, AccountId, f'key/{key_id}'])]
        else:
            resource = ['*']
        return Policy(
            PolicyName='ECSKMSPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Effect': 'Allow',
                        'Action': [
                            'kms:Encrypt',
                            'kms:Decrypt',
                            'kms:ReEncrypt*',
                            'kms:GenerateDataKey*',
                            'kms:DescribeKey'
                        ],
                        'Resource': resource
                    }
                ]
            }
        )

    @staticmethod
    def cloudwatch_logger_policy() -> Policy:
        """ A policy that when attached allows the user to log things to
            any cloudwatch log.
        """
        return Policy(
            PolicyName='ECSCWLoggingAccess',
            PolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "logs:CreateLogGroup",
                            "logs:CreateLogStream",
                            "logs:PutLogEvents",
                            "logs:DescribeLogGroups",
                            "logs:DescribeLogStreams"
                        ],
                        "Resource": "*"
                    }
                ]
            }
        )

    def vcp_flowlog_role(self) -> Role:
        """ Creates a role that can be assumed by the VPC flow logs service
            that gives permission to log to Cloudwatch. Needed to enabled VPC
            flow logs.
        """
        return Role(
            'VPCFlowLogRole',
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'vpc-flow-logs.amazonaws.com'))
                ]
            ),
            Policies=[
                self.cloudwatch_logger_policy()
            ]
        )

    def ecs_assumed_iam_role(self) -> Role:
        """ Builds a general purpose IAM role for use with ECS.
            TODO: split into several roles?
            TODO: add STS GetFederationToken perm
        """
        policies = [
            self.ecs_secret_manager_policy(),  # to get env configuration
            self.ecs_access_policy(),  # to manage ECS
            self.ecs_es_policy(),  # to access ES
            self.ecs_sqs_policy(),  # to access SQS
            self.ecs_log_policy(),  # to log things
            self.ecs_ecr_policy(),  # to pull down container images
            self.ecs_cfn_policy(),  # to pull ECS Service URL from Cloudformation
            self.ecs_s3_policy(),  # for handling raw files
            self.ecs_web_service_policy(),  # permissions for service,
            self.kms_policy(),  # permission to use KMS keys to decrypt
        ]
        return Role(
            self.ROLE_NAME,
            # IMPORTANT: BOTH ECS and EC2 need AssumeRole
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'ecs.amazonaws.com')),
                    Statement(
                        Effect='Allow',
                        Action=[
                            Action('sts', 'AssumeRole')
                        ],
                        Principal=Principal('Service', 'ec2.amazonaws.com')),
                    Statement(
                        Effect='Allow',
                        Action=[
                            Action('sts', 'AssumeRole')
                        ],
                        Principal=Principal('Service', 'ecs-tasks.amazonaws.com'))]),
            Policies=policies
        )

    def ecs_autoscaling_role(self) -> Role:
        """ Assumed IAM Role for autoscaling. """
        return Role(
            self.AUTOSCALING_ROLE_NAME,
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'application-autoscaling.amazonaws.com')
                )]
            ),
            Policies=[self.ecs_autoscaling_access_policy()]
        )

    def dev_user_role(self) -> Role:
        """ Builds a user with "development" permissions, or limited AWS access
            to various aspects of the infrastructure.
        """
        policies = [
            # full control of ECS and associated load balancing
            self.ecs_access_policy(),
            # full control of the ES
            self.ecs_es_policy(),
            # standard s3 perms
            self.ecs_s3_policy(),
            # kms access
            self.kms_policy()
        ]
        return Role(
            self.DEV_ROLE,
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=AWSPrincipal(AccountId)
                )]
            ),
            # we can use 10 of these policies, so these 10 are selected with intention
            # as they are hard to craft reasonably - Will Feb 10 2022
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess',  # read only for logs
                'arn:aws:iam::aws:policy/IAMReadOnlyAccess',  # read only for IAM
                'arn:aws:iam::aws:policy/AmazonRDSReadOnlyAccess',  # read only for RDS
                'arn:aws:iam::aws:policy/AWSCloudFormationReadOnlyAccess',  # read only for cfn
                'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser',  # most perms for ECR
                'arn:aws:iam::aws:policy/AmazonSQSFullAccess',  # full access to sqs (indexing queues)
                'arn:aws:iam::aws:policy/AWSStepFunctionsFullAccess',  # full access for Step Functions (tibanna)
                'arn:aws:iam::aws:policy/AWSLambda_FullAccess',  # full access to lambda (foursight)
                'arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess',  # full perms to codebuild (app version build)
                'arn:aws:iam::aws:policy/AmazonEC2FullAccess'  # full access to EC2 (tibanna)
            ],
            Policies=policies
        )

    def ecs_instance_profile(self) -> InstanceProfile:
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            self.INSTANCE_PROFILE_NAME,
            Roles=[Ref(self.ecs_assumed_iam_role())]
        )

    def ecs_s3_iam_user(self) -> User:
        """ Builds an IAM user for federating access to S3 files. """
        # dmichaels/2022-06-22: Factored out into Names.ecs_s3_iam_user_logical_id() in names.py.
        # logical_id = self.name.logical_id('ApplicationS3Federator')
        logical_id = Names.ecs_s3_iam_user_logical_id(self.name)
        return User(
            logical_id,
            Policies=[
                self.ecs_s3_policy(),
                self.ecs_s3_user_sts_policy(),
                self.kms_policy(),
            ],
            Tags=self.tags.cost_tag_obj(logical_id)
        )

    @staticmethod
    def ecs_s3_iam_user_access_key(s3_iam_user: User) -> AccessKey:
        """ Builds an access key for the S3 IAM User """
        return AccessKey(
            'S3AccessKey', Status='Active', UserName=Ref(s3_iam_user)
        )

    def output_assumed_iam_role_or_user(self, resource, export_name) -> Output:
        """ Creates output for assumed IAM roles/users
            TODO: Standardize output generation into a single method
        """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name)
        )

    def output_instance_profile(self, resource: InstanceProfile):
        """ Creates output for ECS instance profile """
        export_name = C4IAMExports.ECS_INSTANCE_PROFILE
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name)
        )
