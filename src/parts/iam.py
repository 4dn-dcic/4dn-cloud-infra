import logging

from awacs.aws import PolicyDocument, Statement, Action, Principal, AWSPrincipal
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from troposphere import Region, AccountId, Template, Ref, Output, Join
from troposphere.iam import Role, InstanceProfile, ManagedPolicy, Policy, User, AccessKey
from ..base import ConfigManager, Settings
from ..constants import C4IAMBase
from ..part import C4Part
from ..exports import C4Exports, exportify
from ..names import Names


logger = logging.getLogger(__name__)


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
    # Opt-in human direct-access roles. Deliberately NOT named *DevRole* - the existing DEV_ROLE
    # above is a different (much broader) thing and the two must be distinguishable in CloudTrail.
    DIAGNOSE_ROLE = ConfigManager.app_case(if_cgap='CGAPDevDiagnoseRole',
                                           if_ff='FFDevDiagnoseRole',
                                           if_smaht='SMaHTDevDiagnoseRole')
    REMEDIATE_ROLE = ConfigManager.app_case(if_cgap='CGAPPowerRemediateRole',
                                            if_ff='FFPowerRemediateRole',
                                            if_smaht='SMaHTPowerRemediateRole')
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

        # Opt-in human direct-access roles. Adds nothing at all unless explicitly enabled in
        # template.config.json, so the template above is unchanged for every existing deployment.
        self.build_human_access_roles(template)
        return template

    def build_human_access_roles(self, template: Template) -> Template:
        """ Adds the opt-in human direct-access roles (and their shared permission boundary) to
            the template, if and only if they are enabled in config. See the Settings block
            'Human direct-AWS-access role options' for the full switch list.

            This is a no-op by default. It is also a no-op when a role is enabled but no approved
            principal ARNs were supplied, because the alternative - falling back to account-root
            trust, as dev_user_role() does - is what makes such a role assumable by anything in
            the account.
        """
        diagnose_wanted = self._human_access_flag(Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED)
        remediate_wanted = self._human_access_flag(Settings.HUMAN_ACCESS_REMEDIATE_ENABLED)
        if not (diagnose_wanted or remediate_wanted):
            return template

        diagnose_principals = self._human_access_list(Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS)
        remediate_principals = self._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS)
        build_diagnose = diagnose_wanted and bool(diagnose_principals)
        build_remediate = remediate_wanted and bool(remediate_principals)
        if diagnose_wanted and not build_diagnose:
            logger.warning(f'{Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED} is on but'
                           f' {Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS} is empty;'
                           f' not creating {self.DIAGNOSE_ROLE}.')
        if remediate_wanted and not build_remediate:
            logger.warning(f'{Settings.HUMAN_ACCESS_REMEDIATE_ENABLED} is on but'
                           f' {Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS} is empty;'
                           f' not creating {self.REMEDIATE_ROLE}.')
        if not (build_diagnose or build_remediate):
            return template

        boundary = self.human_access_boundary_policy()
        template.add_resource(boundary)
        if build_diagnose:
            diagnose_role = self.human_diagnose_role(diagnose_principals, boundary)
            template.add_resource(diagnose_role)
            template.add_output(self.output_human_access_role(diagnose_role))
        if build_remediate:
            remediate_role = self.human_remediate_role(remediate_principals, boundary)
            template.add_resource(remediate_role)
            template.add_output(self.output_human_access_role(remediate_role))
        return template

    @staticmethod
    def build_sqs_arn(prefix):
        return Join(
            ':', ['arn', 'aws', 'sqs', Region, AccountId, prefix]
        )

    @staticmethod
    def builds_secret_manager_arn(secret_name):
        return Join(
            ':', ['arn', 'aws', 'secretsmanager', Region, AccountId, 'secret', secret_name, '-*']
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

    def ecs_sqs_policy(self, prefix='*') -> Policy:
        """ Grants ECS access to ElasticSearch.
        """
        return Policy(
            PolicyName='ECSSQSAccessPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=dict(
                    Effect='Allow',
                    Action=['sqs:*'],  # TODO: prune this slightly?
                    Resource=[self.build_sqs_arn(prefix)]  # TODO: prune this slightly?
                )
            )
        )

    def ecs_es_policy(self, domain_name=None) -> Policy:
        """ Grants ECS access to ElasticSearch.
        """
        if domain_name is None:
            domain_name = '*'  # TODO: Namespace better, such as 'c4datastore*' but with something that actually matches
        return Policy(
            PolicyName='ECSESAccessPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'es:*',
                    ],
                    Resource=[self.build_elasticsearch_arn(domain_name)]
                )],
            )
        )

    @classmethod
    def ecs_secret_manager_policy(cls) -> Policy:
        """ Provides ECS access to the specified secret.
            The secret ID determines the environment name we are creating.
            TODO: Should this also be created here? Or manually uploaded?
        """
        return Policy(
            PolicyName='ECSSecretManagerPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'secretsmanager:GetSecretValue',  # at least this needed
                        'secretsmanager:GetResourcePolicy',  # these might be overly permissive
                        'secretsmanager:DescribeSecret',
                        'secretsmanager:ListSecretVersionIds'
                    ],
                    Resource=['*']  # XXX: should be self.builds_secret_manager_arn(secret_name) but doesn't work
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
        """ Give ECS access to itself (and loadbalancing APIs). """
        return Policy(
            PolicyName='ECSManagementPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect="Allow",
                    Action=[
                        'ecs:*',
                        'elasticloadbalancing:*',
                    ],
                    Resource=['*'],
                )],
            ),
        )

    @staticmethod
    def ecs_log_policy() -> Policy:
        """ Grants ECS container the ability to log things. """
        return Policy(
            PolicyName='ECSLoggingPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'logs:Create*',
                        'logs:PutLogEvents',
                    ],
                    Resource=['*']  # XXX: Constrain further? Must match WRT log group and AWS logs
                )]
            )
        )

    @staticmethod
    def ecs_ecr_policy() -> Policy:
        """ Policy allowing ECS to pull ECR images. """
        return Policy(
            PolicyName='ECSECRPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        GetAuthorizationToken,
                        GetDownloadUrlForLayer,
                        BatchGetImage,
                        BatchCheckLayerAvailability,
                    ],
                    Resource=['*'],  # XXX: constrain further?
                )],
            ),
        )

    @staticmethod
    def ecs_web_service_policy() -> Policy:
        """ Policy needed by load balancer to allow target group registration. """
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
                        'ec2:AuthorizeSecurityGroupIngress',
                    ],
                    Resource=['*'],  # XXX: constrain further?
                )],
            ),
        )

    @staticmethod
    def ecs_cfn_policy() -> Policy:
        """ Gives access to the DescribeStacks and list stacks API of cloudformation so that Application
            services can read outputs from stacks.

            Associated API: get_ecs_real_url, others within foursight
        """
        return Policy(
            PolicyName='ECSCfnPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'cloudformation:DescribeStacks',
                        'cloudformation:ListStacks'
                    ],
                    Resource=['*'],  # XXX: constrain further?
                )],
            ),
        )

    @staticmethod
    def ecs_s3_policy() -> Policy:
        """ Gives s3 read/write access. """
        return Policy(
            PolicyName='ECSS3Policy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        's3:ListBucket',
                        's3:PutObject',
                        's3:GetObject',
                        's3:DeleteObject',
                    ],
                    Resource=['*'],  # XXX: constrain further?
                )],
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

    @staticmethod
    def kms_policy() -> Policy:
        """ Defines a policy that gives permission access to a subset of actions on KMS.
            Needed for the S3Federator to generate URLs that enable server side encryption. """
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
                        'Resource': [
                            '*'
                        ]
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

    # -------------------------------------------------------------------------------------------
    # Human direct-AWS-access roles (opt-in; nothing below is built unless config enables it)
    #
    #   human_diagnose_role()  - read-only inspection of the running system. Keeps resource-scoped
    #       Secrets Manager and S3 object reads, so a developer can gather evidence, plus the
    #       observability reads needed to answer "is it up, why did it die, is it backed up".
    #   human_remediate_role() - a small set of named, reversible operational writes, each one on
    #       an explicitly supplied resource ARN.
    #
    # These are defined independently of the ecs_*_policy() helpers above on purpose. Sharing
    # those helpers is exactly what makes dev_user_role() a superset of the ECS runtime role, and
    # reusing them here would reintroduce that coupling. dev_user_role() itself is untouched.
    # -------------------------------------------------------------------------------------------

    @staticmethod
    def _human_access_flag(setting: str) -> bool:
        """ Reads a boolean opt-in setting, defaulting to off. ConfigManager already turns the
            strings "true"/"false" into booleans, so tolerate either shape.
        """
        value = ConfigManager.get_config_setting(setting, default=False)
        if isinstance(value, bool):
            return value
        return ConfigManager.str_to_bool(str(value)) is True

    @staticmethod
    def _human_access_list(setting: str) -> list:
        """ Reads a comma-separated (or newline-separated) config setting as a list of strings,
            defaulting to empty. Empty means "this capability is not granted".
        """
        value = ConfigManager.get_config_setting(setting, default='')
        if not value or value is True:
            return []
        items = value if isinstance(value, list) else str(value).replace('\n', ',').split(',')
        return [item.strip() for item in items if str(item).strip()]

    @staticmethod
    def _region_pin() -> dict:
        """ Condition restricting a statement to the region this stack is deployed in. """
        return {'StringEquals': {'aws:RequestedRegion': Region}}

    @staticmethod
    def _human_access_require_mfa() -> bool:
        """ Whether to assert aws:MultiFactorAuthPresent. Defaults to True; set
            human_access.require_mfa to false only for IAM Identity Center (SSO) accounts, where
            MFA is asserted upstream at the IdP and this condition key cannot be relied on. Note
            that a condition on a key absent from the request evaluates false, so leaving this on
            in an SSO account fails closed rather than open.
        """
        value = ConfigManager.get_config_setting(Settings.HUMAN_ACCESS_REQUIRE_MFA, default=True)
        if isinstance(value, bool):
            return value
        return ConfigManager.str_to_bool(str(value)) is not False

    @classmethod
    def _human_access_mutation_condition(cls) -> dict:
        """ Conditions attached to every remediation write: this region, and normally a live MFA
            session.
        """
        condition = cls._region_pin()
        if cls._human_access_require_mfa():
            condition['Bool'] = {'aws:MultiFactorAuthPresent': 'true'}
        return condition

    @staticmethod
    def _build_log_group_arns(prefix: str) -> list:
        """ Log groups created by this repo have no LogGroupName, so CloudFormation generates
            '<stack-name>-<LogicalId>-<random>' and the ARN can only be matched by prefix.
        """
        return [
            Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group', f'{prefix}*']),
            Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group', f'{prefix}*', 'log-stream', '*']),
        ]

    @staticmethod
    def _build_kms_key_arn(key_id: str):
        return Join(':', ['arn', 'aws', 'kms', Region, AccountId, f'key/{key_id}'])

    @staticmethod
    def _build_iam_role_arn(name_pattern: str):
        return Join(':', ['arn', 'aws', 'iam', '', AccountId, f'role/{name_pattern}'])

    @classmethod
    def human_access_log_group_prefix(cls) -> str:
        """ The logging stack's name, which every application log group's physical name starts
            with. The logging part is ecosystem-shared (see C4Logging.SHARING).
        """
        from .logging import C4Logging  # deferred: avoids an import cycle between IAM and logging
        return f'{C4Logging.suggest_stack_name().stack_name}-'

    @classmethod
    def human_access_rds_log_group_arns(cls) -> list:
        """ RDS publishes to /aws/rds/instance/<DBInstanceIdentifier>/..., where the identifier is
            rds.name if configured, else rds-{env_name} (see C4Datastore.rds_instance).
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        rds_name = ConfigManager.get_config_setting(Settings.RDS_NAME, default=None) or f'rds-{env_name}'
        return cls._build_log_group_arns(f'/aws/rds/instance/{rds_name}/')

    @classmethod
    def human_access_secret_arns(cls) -> list:
        """ The two secrets a developer needs to read to explain application behaviour: the
            application configuration (GAC) and the RDS master secret. Names come from names.py,
            so these are the real identifiers rather than a guessed prefix.
        """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return [
            cls.builds_secret_manager_arn(Names.application_configuration_secret(env_name)),
            cls.builds_secret_manager_arn(Names.rds_secret_logical_id(env_name)),
        ]

    @classmethod
    def human_access_bucket_names(cls) -> list:
        """ Buckets the diagnostic role may read objects from. Defaults to this deployment's own
            derived application and foursight buckets; override with an explicit list where the
            bucket names are legacy and do not follow the derived pattern (some do not).
        """
        configured = cls._human_access_list(Settings.HUMAN_ACCESS_DIAGNOSE_BUCKETS)
        if configured:
            return configured
        templates = [
            ConfigManager.AppBucketTemplate.BLOBS,
            ConfigManager.AppBucketTemplate.FILES,
            ConfigManager.AppBucketTemplate.WFOUT,
            ConfigManager.AppBucketTemplate.SYSTEM,
            ConfigManager.AppBucketTemplate.METADATA_BUNDLES,
            ConfigManager.AppBucketTemplate.TIBANNA_OUTPUT,
            ConfigManager.AppBucketTemplate.TIBANNA_CWL,
            ConfigManager.FSBucketTemplate.ENVS,
            ConfigManager.FSBucketTemplate.RESULTS,
            ConfigManager.FSBucketTemplate.APPLICATION_VERSIONS,
        ]
        return [ConfigManager.resolve_bucket_name(template) for template in templates]

    @classmethod
    def human_access_bucket_arns(cls) -> list:
        return [f'arn:aws:s3:::{name}' for name in cls.human_access_bucket_names()]

    @classmethod
    def human_access_object_arns(cls) -> list:
        return [f'arn:aws:s3:::{name}/*' for name in cls.human_access_bucket_names()]

    @classmethod
    def human_access_kms_key_arns(cls) -> list:
        """ The single configured S3 server-side-encryption key, or nothing. Never a wildcard. """
        key_id = ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None)
        return [cls._build_kms_key_arn(key_id)] if key_id else []

    def human_access_trust_policy(self, principal_arns: list) -> dict:
        """ Trust policy for a human-access role: only the enumerated principal ARNs, only with an
            attributable session.

            Deliberately NOT AWSPrincipal(AccountId): account-root trust in a role's trust policy
            means any identity in the account holding sts:AssumeRole can assume it, which is how
            dev_user_role() is reachable today.

            Note on session length: MaxSessionDuration on the role is the control, not a condition
            key. There is no sts:DurationSeconds condition key, and asserting a non-existent key
            would evaluate false and make the role unassumable.
        """
        condition = {}
        if self._human_access_require_mfa():
            condition['Bool'] = {'aws:MultiFactorAuthPresent': 'true'}
            condition['NumericLessThan'] = {'aws:MultiFactorAuthAge': '3600'}
        source_identity_pattern = ConfigManager.get_config_setting(
            Settings.HUMAN_ACCESS_SOURCE_IDENTITY_PATTERN, default=None)
        if source_identity_pattern:
            condition['StringLike'] = {'sts:SourceIdentity': source_identity_pattern}
        allow_statement = {
            'Sid': 'ApprovedHumanPrincipalsOnly',
            'Effect': 'Allow',
            'Principal': {'AWS': principal_arns},
            'Action': ['sts:AssumeRole', 'sts:SetSourceIdentity'],
        }
        if condition:
            allow_statement['Condition'] = condition
        return {
            'Version': '2012-10-17',
            'Statement': [
                allow_statement,
                {
                    # Every session must be attributable to a person in CloudTrail.
                    'Sid': 'DenyAssumeWithoutSourceIdentity',
                    'Effect': 'Deny',
                    'Principal': {'AWS': '*'},
                    'Action': 'sts:AssumeRole',
                    'Condition': {'Null': {'sts:SourceIdentity': 'true'}},
                },
            ],
        }

    @classmethod
    def human_access_region_deny_statement(cls) -> dict:
        """ Deny anything outside this region. Global services are excepted because they are only
            reachable through us-east-1 and denying them would break sts/iam self-inspection.
        """
        return {
            'Sid': 'DenyOutsideHomeRegionExceptGlobalServices',
            'Effect': 'Deny',
            'NotAction': ['iam:*', 'sts:*', 'cloudfront:*', 'route53:*', 's3:ListAllMyBuckets',
                          'support:*', 'organizations:*', 'health:*', 'budgets:*', 'ce:*'],
            'Resource': '*',
            'Condition': {'StringNotEquals': {'aws:RequestedRegion': Region}},
        }

    def human_access_boundary_policy(self) -> ManagedPolicy:
        """ Permission boundary shared by both human-access roles.

            This is the backstop that keeps a future additive edit to either role from quietly
            granting identity administration, supply-chain writes, or data-plane writes. It is not
            a substitute for the Deny statements on the roles themselves: a boundary caps the
            role's own effective permissions and is neither inherited nor applied to
            resource-based policies.

            Where the roles are meant to have a narrow read (S3 objects, the two application
            secrets, the one encryption key), the boundary denies the action everywhere *except*
            those resources via NotResource, rather than dropping the deny altogether.
        """
        statements = [
            {'Sid': 'AllowWhatIsNotExplicitlyForbidden', 'Effect': 'Allow',
             'Action': '*', 'Resource': '*'},
            {
                'Sid': 'NeverIdentityOrgOrBillingAdministration',
                'Effect': 'Deny',
                'Action': [
                    'iam:Create*', 'iam:Delete*', 'iam:Update*', 'iam:Put*', 'iam:Attach*',
                    'iam:Detach*', 'iam:Add*', 'iam:Remove*', 'iam:Set*', 'iam:Tag*',
                    'iam:Untag*', 'iam:ChangePassword', 'iam:PassRole',
                    'sso:*', 'sso-admin:*', 'sso-directory:*', 'identitystore:*',
                    'organizations:*', 'account:*', 'aws-portal:*', 'billing:*', 'ce:*',
                    'budgets:*', 'cur:*', 'sts:GetFederationToken',
                ],
                'Resource': '*',
            },
            {
                'Sid': 'NeverCodeSupplyChainOrArbitraryExecution',
                'Effect': 'Deny',
                'Action': [
                    'ecr:PutImage', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
                    'ecr:CompleteLayerUpload', 'ecr:BatchDeleteImage', 'ecr:DeleteRepository',
                    'ecr:SetRepositoryPolicy', 'ecr:PutImageTagMutability',
                    'ecs:RegisterTaskDefinition', 'ecs:DeregisterTaskDefinition',
                    'ecs:CreateService', 'ecs:DeleteService', 'ecs:CreateCluster',
                    'ecs:DeleteCluster', 'ecs:RunTask', 'ecs:StartTask', 'ecs:ExecuteCommand',
                    'lambda:CreateFunction', 'lambda:DeleteFunction', 'lambda:UpdateFunctionCode',
                    'lambda:UpdateFunctionConfiguration', 'lambda:InvokeFunction',
                    'lambda:AddPermission', 'lambda:AddLayerVersionPermission',
                    'codebuild:CreateProject', 'codebuild:UpdateProject',
                    'codebuild:DeleteProject', 'codebuild:UpdateProjectVisibility',
                    'states:CreateStateMachine', 'states:UpdateStateMachine',
                    'states:DeleteStateMachine',
                    'ssm:SendCommand', 'ssm:StartSession',
                ],
                'Resource': '*',
            },
            {
                'Sid': 'NeverInfrastructureOrPerimeterMutation',
                'Effect': 'Deny',
                'Action': [
                    'cloudformation:CreateStack', 'cloudformation:UpdateStack',
                    'cloudformation:DeleteStack', 'cloudformation:CreateChangeSet',
                    'cloudformation:ExecuteChangeSet', 'cloudformation:SetStackPolicy',
                    'cloudformation:UpdateTerminationProtection', 'cloudformation:CreateStackSet',
                    'cloudformation:UpdateStackSet', 'cloudformation:CreateStackInstances',
                    'ec2:AuthorizeSecurityGroup*', 'ec2:RevokeSecurityGroup*',
                    'ec2:CreateSecurityGroup', 'ec2:DeleteSecurityGroup',
                    'ec2:ModifySecurityGroupRules', 'ec2:*Vpc*', 'ec2:*Subnet*', 'ec2:*Route*',
                    'ec2:*InternetGateway*', 'ec2:*NatGateway*', 'ec2:*NetworkAcl*',
                    'ec2:RunInstances', 'ec2:TerminateInstances',
                    'elasticloadbalancing:Create*', 'elasticloadbalancing:Delete*',
                    'elasticloadbalancing:Modify*', 'elasticloadbalancing:Set*',
                    'es:Create*', 'es:Delete*', 'es:Update*',
                    'rds:Create*', 'rds:Delete*', 'rds:Modify*', 'rds:Restore*', 'rds:Reboot*',
                    'rds:Stop*', 'rds:Start*', 'rds:Promote*', 'rds:Copy*',
                    'elasticache:Delete*', 'elasticache:Modify*',
                    'cloudtrail:StopLogging', 'cloudtrail:DeleteTrail', 'cloudtrail:UpdateTrail',
                    'cloudtrail:PutEventSelectors', 'config:DeleteConfigRule',
                    'config:StopConfigurationRecorder', 'guardduty:DeleteDetector',
                    'guardduty:UpdateDetector',
                    'logs:DeleteLogGroup', 'logs:DeleteLogStream',
                ],
                'Resource': '*',
            },
            {
                'Sid': 'NeverDataPlaneWrites',
                'Effect': 'Deny',
                'Action': [
                    's3:PutObject*', 's3:DeleteObject*', 's3:DeleteBucket', 's3:PutBucket*',
                    's3:PutEncryptionConfiguration', 's3:PutLifecycleConfiguration',
                    's3:PutReplicationConfiguration',
                    'secretsmanager:PutSecretValue', 'secretsmanager:UpdateSecret',
                    'secretsmanager:DeleteSecret', 'secretsmanager:RotateSecret',
                    'secretsmanager:PutResourcePolicy', 'secretsmanager:DeleteResourcePolicy',
                    'kms:PutKeyPolicy', 'kms:ScheduleKeyDeletion', 'kms:DisableKey',
                    'kms:CreateGrant', 'kms:RetireGrant', 'kms:RevokeGrant',
                    'ssm:PutParameter', 'ssm:DeleteParameter',
                    'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem',
                    'es:ESHttpPost', 'es:ESHttpPut', 'es:ESHttpDelete', 'es:ESHttpPatch',
                ],
                'Resource': '*',
            },
        ]
        # Reads the roles are meant to have, denied everywhere but on those exact resources.
        statements.append(self._boundary_scoped_read_deny(
            'BoundS3ObjectReadsToApplicationBuckets',
            ['s3:GetObject', 's3:GetObjectVersion', 's3:GetObjectTagging', 's3:GetObjectTorrent'],
            self.human_access_object_arns()))
        statements.append(self._boundary_scoped_read_deny(
            'BoundSecretReadsToApplicationSecrets',
            ['secretsmanager:GetSecretValue'],
            self.human_access_secret_arns()))
        statements.append(self._boundary_scoped_read_deny(
            'BoundKmsUseToConfiguredEncryptionKey',
            ['kms:Decrypt', 'kms:GenerateDataKey', 'kms:GenerateDataKeyWithoutPlaintext',
             'kms:ReEncryptFrom'],
            self.human_access_kms_key_arns()))
        statements.append(self.human_access_region_deny_statement())
        return ManagedPolicy(
            self.name.logical_id('HumanAccessBoundary'),
            Description='Permission boundary for the opt-in human direct-access roles.',
            PolicyDocument={'Version': '2012-10-17', 'Statement': statements},
        )

    @staticmethod
    def _boundary_scoped_read_deny(sid: str, actions: list, allowed_resources: list) -> dict:
        """ Deny these actions everywhere except on allowed_resources; if there is nothing to
            carve out, deny them outright.
        """
        statement = {'Sid': sid, 'Effect': 'Deny', 'Action': actions}
        if allowed_resources:
            statement['NotResource'] = allowed_resources
        else:
            statement['Resource'] = '*'
        return statement

    @classmethod
    def human_diagnose_observability_policy(cls) -> Policy:
        """ The service-specific read APIs needed to inspect a running deployment. Almost all of
            these Describe/List/Get APIs have no resource-level authorization at all, so they are
            on '*' and constrained by region instead.

            cloudformation:Detect* is deliberately absent: drift detection starts a job, which is
            not a read, and it is not needed to inspect a service.
        """
        return Policy(
            PolicyName='HumanDiagnoseObservabilityPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'RegionPinnedServiceStateReads',
                    'Effect': 'Allow',
                    'Action': [
                        'sts:GetCallerIdentity',
                        'ecs:Describe*', 'ecs:List*',
                        'elasticloadbalancing:Describe*',
                        'application-autoscaling:Describe*',
                        'cloudwatch:Describe*', 'cloudwatch:Get*', 'cloudwatch:List*',
                        'logs:Describe*', 'logs:List*',
                        'rds:Describe*', 'rds:ListTagsForResource',
                        'es:Describe*', 'es:List*', 'es:Get*',
                        'sqs:GetQueueAttributes', 'sqs:GetQueueUrl', 'sqs:ListQueues',
                        'elasticache:Describe*', 'elasticache:List*',
                        'cloudformation:Describe*', 'cloudformation:List*', 'cloudformation:Get*',
                        'ecr:Describe*', 'ecr:List*', 'ecr:GetLifecyclePolicy',
                        'ecr:GetRepositoryPolicy', 'ecr:BatchGetImage',
                        'ecr:GetAuthorizationToken',
                        'codebuild:BatchGet*', 'codebuild:List*',
                        'states:Describe*', 'states:List*', 'states:GetExecutionHistory',
                        'lambda:GetPolicy', 'lambda:GetAlias', 'lambda:List*',
                        'ec2:Describe*',
                        'servicequotas:Get*', 'servicequotas:List*',
                        'tag:GetResources', 'tag:GetTagKeys', 'tag:GetTagValues',
                        'secretsmanager:ListSecrets',
                        # Key metadata only - no key material and no ciphertext access. Needed to
                        # answer "is this bucket encrypted, and with which key": the key ARN comes
                        # from s3:GetEncryptionConfiguration, so it cannot be scoped in advance,
                        # and buckets may use AWS-managed keys that no config setting names. The
                        # more revealing kms:GetKeyPolicy stays scoped to the configured key below.
                        'kms:DescribeKey', 'kms:GetKeyRotationStatus', 'kms:ListAliases',
                    ],
                    'Resource': '*',
                    'Condition': cls._region_pin(),
                }],
            },
        )

    def human_diagnose_resource_read_policy(self) -> Policy:
        """ The resource-scoped half of diagnosis: application logs, the application buckets, the
            two application secrets, encryption-key metadata, and this role's own definition.

            Secrets Manager and S3 object reads are retained here on purpose - a developer is
            expected to inspect the system and bring evidence - but only on the specific secrets
            and buckets this deployment owns, never on '*'.
        """
        statements = [
            {
                'Sid': 'ReadApplicationAndDatabaseLogs',
                'Effect': 'Allow',
                'Action': [
                    'logs:FilterLogEvents', 'logs:GetLogEvents', 'logs:GetLogGroupFields',
                    'logs:GetLogRecord', 'logs:StartQuery', 'logs:StopQuery',
                    'logs:GetQueryResults',
                ],
                'Resource': (self._build_log_group_arns(self.human_access_log_group_prefix())
                             + self.human_access_rds_log_group_arns()),
            },
            {
                'Sid': 'InspectApplicationBucketConfiguration',
                'Effect': 'Allow',
                'Action': [
                    's3:ListBucket', 's3:GetBucketLocation', 's3:GetBucketVersioning',
                    's3:GetBucketPolicy', 's3:GetBucketPolicyStatus',
                    's3:GetEncryptionConfiguration', 's3:GetLifecycleConfiguration',
                    's3:GetBucketPublicAccessBlock', 's3:GetBucketTagging', 's3:GetBucketCORS',
                ],
                'Resource': self.human_access_bucket_arns(),
            },
            {
                'Sid': 'ReadObjectsInApplicationBucketsOnly',
                'Effect': 'Allow',
                'Action': ['s3:GetObject', 's3:GetObjectVersion', 's3:GetObjectTagging'],
                'Resource': self.human_access_object_arns(),
            },
            {
                'Sid': 'ReadApplicationSecretsOnly',
                'Effect': 'Allow',
                'Action': [
                    'secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret',
                    'secretsmanager:ListSecretVersionIds', 'secretsmanager:GetResourcePolicy',
                ],
                'Resource': self.human_access_secret_arns(),
            },
            {
                'Sid': 'InspectOwnRoleDefinition',
                'Effect': 'Allow',
                'Action': ['iam:GetRole', 'iam:GetRolePolicy', 'iam:ListRolePolicies',
                           'iam:ListAttachedRolePolicies'],
                'Resource': self._build_iam_role_arn(f'{self.name.stack_name}-*'),
            },
        ]
        kms_key_arns = self.human_access_kms_key_arns()
        if kms_key_arns:
            # Key-policy reads (and optionally Decrypt) on the one configured key. Plain key
            # metadata is granted region-pinned in the observability policy instead, so that
            # "which key encrypts this bucket" is still answerable when no key is configured here.
            kms_actions = ['kms:GetKeyPolicy']
            if self._human_access_flag(Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT):
                # Needed to read objects in an SSE-KMS bucket. KMS requires dual authorization, so
                # this grant is inert until the key policy also names this role - which is a
                # separate, out-of-band change, not something this template can make.
                kms_actions.append('kms:Decrypt')
            statements.append({
                'Sid': 'ConfiguredEncryptionKeyOnly',
                'Effect': 'Allow',
                'Action': kms_actions,
                'Resource': kms_key_arns,
            })
        return Policy(
            PolicyName='HumanDiagnoseResourceReadPolicy',
            PolicyDocument={'Version': '2012-10-17', 'Statement': statements},
        )

    @classmethod
    def human_diagnose_guardrail_policy(cls) -> Policy:
        """ Explicit denies that make the diagnostic role read-only in its own right, rather than
            relying on the absence of an Allow (or on the boundary staying attached).

            sts:AssumeRole is denied so this role cannot be used as a stepping stone to the
            remediation role or to the ECS runtime role - each privilege increase has to be a
            fresh, separately audited assume from the human's own identity.
        """
        actions = [
            's3:PutObject', 's3:DeleteObject', 's3:PutObjectAcl',
            'secretsmanager:PutSecretValue', 'secretsmanager:UpdateSecret',
            'secretsmanager:DeleteSecret', 'secretsmanager:RotateSecret',
            'ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath',
            # Postgres logs can carry query text, and therefore data.
            'rds:DownloadDBLogFilePortion', 'rds:DownloadCompleteDBLogFile',
            'dynamodb:GetItem', 'dynamodb:Query', 'dynamodb:Scan',
            # Queue depth comes from GetQueueAttributes; message bodies are application data.
            'sqs:ReceiveMessage', 'sqs:SendMessage', 'sqs:DeleteMessage', 'sqs:PurgeQueue',
            # GetFunctionConfiguration returns environment variables and GetFunction returns a
            # presigned code download URL; both are configuration exfiltration paths.
            'lambda:GetFunction', 'lambda:GetFunctionConfiguration', 'lambda:InvokeFunction',
            'es:ESHttp*',
            'ecs:UpdateService', 'ecs:StopTask', 'ecs:RunTask', 'ecs:StartTask',
            'ecs:RegisterTaskDefinition', 'ecs:CreateService', 'ecs:DeleteService',
            'ecs:ExecuteCommand',
            'ecr:PutImage', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
            'ecr:CompleteLayerUpload', 'ecr:BatchDeleteImage',
            'codebuild:StartBuild', 'codebuild:StopBuild', 'codebuild:RetryBuild',
            'states:StartExecution', 'states:StopExecution',
            'cloudwatch:PutMetricAlarm', 'cloudwatch:DeleteAlarms', 'cloudwatch:SetAlarmState',
            'logs:PutRetentionPolicy',
            'cloudformation:Detect*',
            'iam:PassRole',
            'sts:AssumeRole', 'sts:AssumeRoleWithSAML', 'sts:AssumeRoleWithWebIdentity',
            'sts:GetFederationToken',
        ]
        if not cls._human_access_flag(Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT):
            actions += ['kms:Decrypt', 'kms:GenerateDataKey', 'kms:GenerateDataKeyWithoutPlaintext',
                        'kms:ReEncryptFrom']
        return Policy(
            PolicyName='HumanDiagnoseGuardrailPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {'Sid': 'DiagnosisIsReadOnly', 'Effect': 'Deny',
                     'Action': actions, 'Resource': '*'},
                    cls.human_access_region_deny_statement(),
                ],
            },
        )

    def human_diagnose_role(self, principal_arns: list, boundary: ManagedPolicy) -> Role:
        """ Read-only diagnosis role. No managed policies are attached: the ten attached to
            dev_user_role() are what make it a superset of the ECS runtime role, and none of them
            is narrow enough to reuse here.
        """
        return Role(
            self.DIAGNOSE_ROLE,
            Description='Read-only diagnosis access for developers. Opt-in; see'
                        ' human_access.* in template.config.json.',
            AssumeRolePolicyDocument=self.human_access_trust_policy(principal_arns),
            MaxSessionDuration=self.HUMAN_ACCESS_DIAGNOSE_SESSION_DURATION,
            PermissionsBoundary=Ref(boundary),
            Policies=[
                self.human_diagnose_observability_policy(),
                self.human_diagnose_resource_read_policy(),
                self.human_diagnose_guardrail_policy(),
            ],
        )

    @classmethod
    def human_remediate_read_policy(cls) -> Policy:
        """ The reads a power user needs to target a remediation safely - you cannot restart a
            service you cannot find, or purge a queue without first confirming its backlog.

            Deliberately narrower than the diagnostic role's reads: no secrets, no S3, no KMS, no
            service quotas, no tag inventory. That keeps CloudTrail cleanly separable into
            "someone was looking" and "someone was changing".
        """
        return Policy(
            PolicyName='HumanRemediateReadPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'ReadsNeededToTargetARemediation',
                    'Effect': 'Allow',
                    'Action': [
                        'sts:GetCallerIdentity',
                        'ecs:Describe*', 'ecs:List*',
                        'elasticloadbalancing:DescribeLoadBalancers',
                        'elasticloadbalancing:DescribeTargetGroups',
                        'elasticloadbalancing:DescribeTargetHealth',
                        'sqs:GetQueueAttributes', 'sqs:GetQueueUrl', 'sqs:ListQueues',
                        'cloudwatch:Describe*', 'cloudwatch:Get*', 'cloudwatch:List*',
                        'logs:Describe*', 'logs:List*',
                        'ecr:Describe*', 'ecr:List*', 'ecr:BatchGetImage',
                        'codebuild:BatchGet*', 'codebuild:List*',
                        'states:Describe*', 'states:List*', 'states:GetExecutionHistory',
                        'cloudformation:Describe*', 'cloudformation:List*',
                        'rds:Describe*', 'es:Describe*', 'es:List*', 'ec2:Describe*',
                    ],
                    'Resource': '*',
                    'Condition': cls._region_pin(),
                }],
            },
        )

    @classmethod
    def human_remediate_action_statements(cls) -> list:
        """ One statement per remediation capability, each built only from explicitly supplied
            resource ARNs. An empty ARN list means the capability is simply absent - there is no
            derived-name or wildcard fallback anywhere in here, which is what keeps an
            unnamed (e.g. live green) environment out of reach.
        """
        statements = []
        condition = cls._human_access_mutation_condition()

        service_arns = cls._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_SERVICE_ARNS)
        if service_arns:
            # Note: IAM has no condition key for the task-definition argument of UpdateService, so
            # this also permits repointing a named service at another already-registered revision.
            # Bounded by ecr:PutImage being denied in the boundary, and by CloudTrail attribution.
            statements.append({
                'Sid': 'RestartOrRescaleNamedServices', 'Effect': 'Allow',
                'Action': ['ecs:UpdateService'], 'Resource': service_arns,
                'Condition': condition,
            })

        cluster_arns = cls._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_CLUSTER_ARNS)
        if cluster_arns:
            task_condition = dict(condition, ArnEquals={'ecs:cluster': cluster_arns})
            statements.append({
                'Sid': 'StopIndividualStuckTasks', 'Effect': 'Allow',
                'Action': ['ecs:StopTask'],
                'Resource': [cls._task_arn_for_cluster(arn) for arn in cluster_arns],
                'Condition': task_condition,
            })

        queue_arns = cls._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_QUEUE_ARNS)
        if queue_arns:
            statements.append({
                'Sid': 'ReleaseInFlightQueueMessages', 'Effect': 'Allow',
                'Action': ['sqs:ChangeMessageVisibility'], 'Resource': queue_arns,
                'Condition': condition,
            })
            if cls._human_access_flag(Settings.HUMAN_ACCESS_REMEDIATE_ALLOW_QUEUE_PURGE):
                # Irreversible: purged messages are gone. Its own explicit, default-off switch.
                statements.append({
                    'Sid': 'PurgeNamedQueues', 'Effect': 'Allow',
                    'Action': ['sqs:PurgeQueue'], 'Resource': queue_arns,
                    'Condition': condition,
                })

        state_machine_arns = cls._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_STATE_MACHINE_ARNS)
        if state_machine_arns:
            statements.append({
                'Sid': 'StartNamedStateMachines', 'Effect': 'Allow',
                'Action': ['states:StartExecution'], 'Resource': state_machine_arns,
                'Condition': condition,
            })
            statements.append({
                'Sid': 'StopExecutionsOfNamedStateMachines', 'Effect': 'Allow',
                'Action': ['states:StopExecution'],
                'Resource': [cls._execution_arn_for_state_machine(arn) for arn in state_machine_arns],
                'Condition': condition,
            })

        codebuild_arns = cls._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_CODEBUILD_ARNS)
        if codebuild_arns:
            # Rebuilding through CI is the only sanctioned way to change what runs: the build runs
            # under CodeBuild's own role from the pinned repo/branch, and the human never pushes
            # an image (ecr:PutImage is denied).
            statements.append({
                'Sid': 'RebuildApplicationImageViaCiOnly', 'Effect': 'Allow',
                'Action': ['codebuild:StartBuild', 'codebuild:StopBuild', 'codebuild:RetryBuild'],
                'Resource': codebuild_arns, 'Condition': condition,
            })
        return statements

    @staticmethod
    def _task_arn_for_cluster(cluster_arn: str) -> str:
        """ arn:aws:ecs:<region>:<acct>:cluster/<name> -> arn:aws:ecs:<region>:<acct>:task/<name>/*
        """
        return cluster_arn.replace(':cluster/', ':task/', 1) + '/*'

    @staticmethod
    def _execution_arn_for_state_machine(state_machine_arn: str) -> str:
        """ ...:stateMachine:<name> -> ...:execution:<name>:* (the resource StopExecution takes).
        """
        return state_machine_arn.replace(':stateMachine:', ':execution:', 1) + ':*'

    @classmethod
    def human_remediate_guardrail_policy(cls) -> Policy:
        """ Denies that hold whether or not the boundary is attached: no way to author or run new
            code, no data or secret reads, and no chaining to another role.
        """
        return Policy(
            PolicyName='HumanRemediateGuardrailPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Sid': 'RemediationCannotSupplyCodeOrReadData',
                        'Effect': 'Deny',
                        'Action': [
                            'ecs:RegisterTaskDefinition', 'ecs:DeregisterTaskDefinition',
                            'ecs:CreateService', 'ecs:DeleteService', 'ecs:CreateCluster',
                            'ecs:DeleteCluster', 'ecs:RunTask', 'ecs:StartTask',
                            'ecs:ExecuteCommand',
                            'ecr:PutImage', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
                            'ecr:CompleteLayerUpload', 'ecr:BatchDeleteImage',
                            'ecr:PutImageTagMutability',
                            'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration',
                            'lambda:InvokeFunction', 'lambda:GetFunction',
                            'lambda:GetFunctionConfiguration',
                            's3:GetObject', 's3:GetObjectVersion', 's3:PutObject',
                            's3:DeleteObject',
                            'secretsmanager:GetSecretValue',
                            'kms:Decrypt', 'kms:GenerateDataKey',
                            'kms:GenerateDataKeyWithoutPlaintext', 'kms:ReEncryptFrom',
                            'ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath',
                            'sqs:ReceiveMessage', 'sqs:SendMessage', 'sqs:DeleteMessage',
                            'rds:DownloadDBLogFilePortion', 'rds:DownloadCompleteDBLogFile',
                            'es:ESHttp*',
                            'iam:PassRole',
                            'sts:AssumeRole', 'sts:AssumeRoleWithSAML',
                            'sts:AssumeRoleWithWebIdentity', 'sts:GetFederationToken',
                        ],
                        'Resource': '*',
                    },
                    cls.human_access_region_deny_statement(),
                ],
            },
        )

    def human_remediate_role(self, principal_arns: list, boundary: ManagedPolicy) -> Role:
        """ Scoped remediation role. Like the diagnostic role it attaches no managed policies and
            shares nothing with the ECS runtime role's helpers.
        """
        policies = [self.human_remediate_read_policy()]
        action_statements = self.human_remediate_action_statements()
        if action_statements:
            policies.append(Policy(
                PolicyName='HumanRemediateActionPolicy',
                PolicyDocument={'Version': '2012-10-17', 'Statement': action_statements},
            ))
        else:
            logger.warning(f'{Settings.HUMAN_ACCESS_REMEDIATE_ENABLED} is on but no remediation'
                           f' target ARNs were supplied; {self.REMEDIATE_ROLE} will be read-only.')
        policies.append(self.human_remediate_guardrail_policy())
        return Role(
            self.REMEDIATE_ROLE,
            Description='Scoped remediation access for power users. Opt-in; see'
                        ' human_access.* in template.config.json.',
            AssumeRolePolicyDocument=self.human_access_trust_policy(principal_arns),
            MaxSessionDuration=self.HUMAN_ACCESS_REMEDIATE_SESSION_DURATION,
            PermissionsBoundary=Ref(boundary),
            Policies=policies,
        )

    def output_human_access_role(self, role: Role) -> Output:
        """ Outputs a human-access role name. Not exported: no other stack consumes these, and an
            export would add a cross-stack dependency to an opt-in feature.
        """
        return Output(
            self.name.logical_id(f'{role.title}Name'),
            Description=f'Name of the {role.title} human direct-access role',
            Value=Ref(role),
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
