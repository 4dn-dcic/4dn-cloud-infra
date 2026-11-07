import ast
import json
import logging
import re

from awacs.aws import PolicyDocument, Statement, Action, Principal, AWSPrincipal
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from troposphere import Region, AccountId, Template, Ref, Output, Join, GetAtt
from troposphere.iam import Role, InstanceProfile, ManagedPolicy, Policy, User, AccessKey
from ..base import ConfigManager, Settings
from ..constants import C4IAMBase, COMMON_STACK_PREFIX
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
    # Only exported when the opt-in deployment role is built; the datastore key policy imports it.
    HUMAN_DEPLOY_ROLE_ARN = exportify('HumanDeployRoleArn')

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
    DEPLOY_ROLE = ConfigManager.app_case(if_cgap='CGAPInfraDeployRole',
                                         if_ff='FFInfraDeployRole',
                                         if_smaht='SMaHTInfraDeployRole')
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
        # custom/config.json, so the template above is unchanged for every existing deployment.
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
        self.build_human_deploy_role(template)
        diagnose_wanted = self._human_access_flag(Settings.HUMAN_ACCESS_DIAGNOSE_ENABLED)
        remediate_wanted = self._human_access_flag(Settings.HUMAN_ACCESS_REMEDIATE_ENABLED)
        if not (diagnose_wanted or remediate_wanted):
            return template

        diagnose_principals = (self._human_access_list(Settings.HUMAN_ACCESS_DIAGNOSE_PRINCIPALS)
                               if diagnose_wanted else [])
        remediate_principals = (self._human_access_list(Settings.HUMAN_ACCESS_REMEDIATE_PRINCIPALS)
                                if remediate_wanted else [])
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
    # -------------------------------------------------------------------------------------------
    # Human direct-AWS-access roles (opt-in; nothing below is built unless config enables it)
    #
    #   human_diagnose_role()  - read-only inspection of the running system.
    #   human_remediate_role() - the operational actions needed to remediate those same services.
    #
    # Scoping model. This account holds only our own resources, so these policies do not enumerate
    # resource identifiers. Where an action supports resource-level authorization it is scoped to
    # the *service* - every ECS service, every queue, every bucket in this account and region - and
    # the real constraint is the action list, which is deliberately short and enumerated. Remaining
    # discovery/inspection requests use '*' (see WILDCARD_READ_SIDS), with a region pin and an
    # account restriction wherever AWS supplies resource ownership. Neither role grants Action '*'.
    #
    # These are defined independently of the ecs_*_policy() helpers above on purpose. Sharing those
    # helpers is exactly what makes dev_user_role() a superset of the ECS runtime role, and reusing
    # them here would reintroduce that coupling. dev_user_role() itself is untouched.
    # -------------------------------------------------------------------------------------------

    # Wildcard discovery/inspection groups. Do not infer AWS authorization semantics from the Sid:
    # some reads support ARNs, while inventory or composite-alarm requests require '*'.
    WILDCARD_READ_SIDS = (
        'InspectServiceStateAcrossSupportedServices',
        'ReadsNeededToTargetARemediation',
    )

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
        if value is None or value == '' or value is False:
            return []
        # ConfigManager._load_config stringifies JSON values, including lists, with str().
        # Parse only a literal list; never evaluate arbitrary config text.
        if isinstance(value, str) and value.lstrip().startswith('['):
            try:
                value = ast.literal_eval(value)
            except (ValueError, SyntaxError) as error:
                raise ValueError(f'{setting} must contain concrete IAM user or role ARNs.') from error
        if not isinstance(value, (str, list)):
            raise ValueError(f'{setting} must contain concrete IAM user or role ARNs.')
        items = value if isinstance(value, list) else value.replace('\n', ',').split(',')
        principals = []
        for item in items:
            if not isinstance(item, str):
                raise ValueError(f'{setting} must contain concrete IAM user or role ARNs.')
            item = item.strip()
            if not item:
                continue
            # Never accept root, account IDs, wildcards, service principals or STS sessions.
            # Cross-account trust is possible, but must name a specific approved user/role.
            if not re.fullmatch(r'arn:aws:iam::[0-9]{12}:(?:user|role)/'
                                r'(?:[A-Za-z0-9_+=,.@-]+/)*[A-Za-z0-9_+=,.@-]+', item):
                raise ValueError(f'{setting} must contain concrete commercial-AWS IAM user or role ARNs.')
            if item not in principals:
                principals.append(item)
        return principals

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

    @staticmethod
    def _region_pin() -> dict:
        """ Condition restricting a statement to the region this stack is deployed in. """
        return {'StringEquals': {'aws:RequestedRegion': Region}}

    @classmethod
    def _human_access_mutation_condition(cls) -> dict:
        """ Region-pin every remediation write. MFA is enforced when assuming the role, not on
            downstream calls: AssumeRole credentials do not carry MFA context for API checks.
            See IAM's 'Secure API access with MFA' documentation.
        """
        return cls._region_pin()

    @staticmethod
    def human_access_s3_account_deny_statement() -> dict:
        """ S3 ARNs have no account field. Explicitly deny other owners, including resource-policy
            grants to a role session which could bypass an identity policy's implicit deny.
        """
        return {
            'Sid': 'DenyS3OutsideThisAccount',
            'Effect': 'Deny',
            'Action': 's3:*',
            'Resource': ['arn:aws:s3:::*', 'arn:aws:s3:::*/*'],
            'Condition': {'StringNotEquals': {'s3:ResourceAccount': AccountId}},
        }

    @staticmethod
    def _service_arn(service: str, suffix: str):
        """ Builds a service-level ARN in this account and region, e.g. 'ecs' + 'service/*'. """
        return Join(':', ['arn', 'aws', service, Region, AccountId, suffix])

    @staticmethod
    def _log_group_arns():
        """ Every log group in this account and region, plus their streams. Log groups here are
            created without an explicit LogGroupName (see C4Logging.build_log_group), so their
            physical names are CloudFormation-generated and could not be enumerated anyway.
        """
        return [
            Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group', '*']),
            Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group', '*', 'log-stream', '*']),
        ]

    def human_access_trust_policy(self, principal_arns: list) -> dict:
        """ Trust only enumerated principals and require a source-identity audit label. Manually
            supplied labels are not verified identities; correlate the authenticated caller.

            Deliberately NOT AWSPrincipal(AccountId): account-root trust in a role's trust policy
            means any identity in the account holding sts:AssumeRole can assume it, which is how
            dev_user_role() is reachable today. This is the one place identifiers are still
            enumerated, because a trust policy is about people rather than resources.

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
        policy = {
            'Version': '2012-10-17',
            'Statement': [
                allow_statement,
                {
                    # Require a label, without mistaking a caller-supplied value for verified identity.
                    'Sid': 'DenyAssumeWithoutSourceIdentity',
                    'Effect': 'Deny',
                    'Principal': {'AWS': '*'},
                    'Action': 'sts:AssumeRole',
                    'Condition': {'Null': {'sts:SourceIdentity': 'true'}},
                },
            ],
        }
        if len(json.dumps(policy, separators=(',', ':'))) > 2048:
            raise ValueError('Human access trust policy exceeds the default IAM 2048-character limit;'
                             ' reduce the principal list or source-identity pattern.')
        return policy

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

            A boundary is a ceiling, not a grant: effective permissions are the intersection of the
            role's own policies and this one, so it must open with an Allow or the roles would be
            able to do nothing at all. That Allow does not widen either role - each role's own
            policies enumerate a short action list and never use Action '*'.

            This adds explicit direct-API backstops, not a complete future-proof allowlist or an
            information-flow sandbox. It does not constrain separately privileged service roles
            reached through the deliberately retained build/workflow delegation.
        """
        return ManagedPolicy(
            self.name.logical_id('HumanAccessBoundary'),
            Description='Permission boundary (ceiling, not a grant) for the opt-in human'
                        ' direct-access roles.',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {'Sid': 'CeilingOnly', 'Effect': 'Allow', 'Action': '*', 'Resource': '*'},
                    {
                        'Sid': 'NeverIdentityOrgOrBillingAdministration',
                        'Effect': 'Deny',
                        'Action': [
                            'iam:Create*', 'iam:Delete*', 'iam:Update*', 'iam:Put*', 'iam:Attach*',
                            'iam:Detach*', 'iam:Add*', 'iam:Remove*', 'iam:Set*', 'iam:Tag*',
                            'iam:Untag*', 'iam:ChangePassword', 'iam:PassRole',
                            'sso:*', 'sso-directory:*', 'identitystore:*',
                            'organizations:*', 'account:*', 'aws-portal:*', 'billing:*', 'ce:*',
                            'budgets:*', 'cur:*', 'sts:GetFederationToken',
                        ],
                        'Resource': '*',
                    },
                    {
                        'Sid': 'NeverDirectCodeSupplyChainOrExecution',
                        'Effect': 'Deny',
                        'Action': [
                            'ecr:PutImage', 'ecr:InitiateLayerUpload', 'ecr:UploadLayerPart',
                            'ecr:CompleteLayerUpload', 'ecr:BatchDeleteImage',
                            'ecr:DeleteRepository', 'ecr:SetRepositoryPolicy',
                            'ecr:PutImageTagMutability',
                            'ecs:RegisterTaskDefinition', 'ecs:DeregisterTaskDefinition',
                            'ecs:CreateService', 'ecs:DeleteService', 'ecs:CreateCluster',
                            'ecs:DeleteCluster', 'ecs:RunTask', 'ecs:StartTask',
                            'ecs:ExecuteCommand',
                            'lambda:CreateFunction', 'lambda:DeleteFunction',
                            'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration',
                            'lambda:InvokeFunction', 'lambda:AddPermission',
                            'lambda:AddLayerVersionPermission',
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
                            'cloudformation:UpdateTerminationProtection',
                            'cloudformation:CreateStackSet', 'cloudformation:UpdateStackSet',
                            'cloudformation:CreateStackInstances',
                            'ec2:AuthorizeSecurityGroup*', 'ec2:RevokeSecurityGroup*',
                            'ec2:CreateSecurityGroup', 'ec2:DeleteSecurityGroup',
                            # Match mutation verbs, not resource nouns: *Vpc* and *Subnet*
                            # also denied the explicitly allowed DescribeVpcs/DescribeSubnets.
                            'ec2:Create*', 'ec2:Delete*', 'ec2:Modify*', 'ec2:Attach*',
                            'ec2:Detach*', 'ec2:Associate*', 'ec2:Disassociate*', 'ec2:Replace*',
                            'ec2:Accept*', 'ec2:Reject*', 'ec2:Enable*', 'ec2:Disable*',
                            'ec2:RunInstances', 'ec2:TerminateInstances',
                            'elasticloadbalancing:Create*', 'elasticloadbalancing:Delete*',
                            'elasticloadbalancing:Modify*', 'elasticloadbalancing:Set*',
                            'es:Create*', 'es:Delete*', 'es:Update*',
                            'rds:Create*', 'rds:Delete*', 'rds:Modify*', 'rds:Restore*',
                            'rds:Reboot*', 'rds:Stop*', 'rds:Start*', 'rds:Promote*', 'rds:Copy*',
                            'elasticache:Delete*', 'elasticache:Modify*',
                            'cloudtrail:StopLogging', 'cloudtrail:DeleteTrail',
                            'cloudtrail:UpdateTrail', 'cloudtrail:PutEventSelectors',
                            'config:DeleteConfigRule', 'config:StopConfigurationRecorder',
                            'guardduty:DeleteDetector', 'guardduty:UpdateDetector',
                            'logs:DeleteLogGroup', 'logs:DeleteLogStream',
                        ],
                        'Resource': '*',
                    },
                    {
                        'Sid': 'NeverDataPlaneWritesOrIrreversibleOperations',
                        'Effect': 'Deny',
                        'Action': [
                            's3:PutObject*', 's3:DeleteObject*', 's3:DeleteBucket',
                            's3:PutBucket*', 's3:PutEncryptionConfiguration',
                            's3:PutLifecycleConfiguration', 's3:PutReplicationConfiguration',
                            'secretsmanager:PutSecretValue', 'secretsmanager:UpdateSecret',
                            'secretsmanager:DeleteSecret', 'secretsmanager:RotateSecret',
                            'secretsmanager:PutResourcePolicy',
                            'secretsmanager:DeleteResourcePolicy',
                            'kms:PutKeyPolicy', 'kms:ScheduleKeyDeletion', 'kms:DisableKey',
                            'kms:CreateGrant', 'kms:RetireGrant', 'kms:RevokeGrant',
                            'ssm:PutParameter', 'ssm:DeleteParameter',
                            'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem',
                            'es:ESHttpPost', 'es:ESHttpPut', 'es:ESHttpDelete', 'es:ESHttpPatch',
                            # Irreversible, and therefore excluded from remediation entirely.
                            'sqs:PurgeQueue', 'sqs:DeleteQueue',
                        ],
                        'Resource': '*',
                    },
                    self.human_access_region_deny_statement(),
                    self.human_access_s3_account_deny_statement(),
                ],
            },
        )

    @classmethod
    def _scope_inspection_policy(cls, policy: Policy) -> Policy:
        """ Split known resource-authorized reads out of the discovery group. The remaining
            inventory/inspection actions stay region-pinned; account ownership is checked when
            provided by AWS (inventory requests often have no resource-account context).
        """
        statement = policy.PolicyDocument['Statement'][0]
        scoped = {
            'ecs': {
                'cluster/*': ['ecs:DescribeClusters'],
                'service/*': ['ecs:DescribeServices'],
                'task/*': ['ecs:DescribeTasks'],
                'container-instance/*': ['ecs:DescribeContainerInstances'],
            },
            'cloudformation': {'stack/*': [
                'cloudformation:DescribeStacks', 'cloudformation:DescribeStackEvents',
                'cloudformation:DescribeStackResources', 'cloudformation:GetTemplate',
                'cloudformation:GetStackPolicy',
            ]},
            'logs': {'log-group:*': ['logs:DescribeLogStreams']},
            'es': {'domain/*': ['es:DescribeDomain', 'es:DescribeDomains']},
            'rds': {
                'db:*': ['rds:DescribeDBInstances'],
                'pg:*': ['rds:DescribeDBParameters'],
                'snapshot:*': ['rds:DescribeDBSnapshots'],
            },
            'states': {'stateMachine:*': ['states:ListExecutions']},
        }
        for service, resources in scoped.items():
            for resource, actions in resources.items():
                selected = [action for action in actions if action in statement['Action']]
                if not selected:
                    continue
                statement['Action'] = [a for a in statement['Action'] if a not in selected]
                policy.PolicyDocument['Statement'].append({
                    'Sid': 'Inspect' + re.sub('[^a-zA-Z0-9]', '', service + resource),
                    'Effect': 'Allow', 'Action': selected,
                    'Resource': cls._service_arn(service, resource),
                    'Condition': cls._region_pin(),
                })
        statement['Condition']['StringEqualsIfExists'] = {'aws:ResourceAccount': AccountId}
        return policy

    @classmethod
    def human_diagnose_observability_policy(cls) -> Policy:
        """ Supported inspection/discovery actions. Resource-authorized reads are separated by
            _scope_inspection_policy; remaining wildcard requests are region-pinned.
            cloudformation:Detect* is absent because drift detection mutates service state.
        """
        return cls._scope_inspection_policy(Policy(
            PolicyName='HumanDiagnoseObservabilityPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'InspectServiceStateAcrossSupportedServices',
                    'Effect': 'Allow',
                    'Action': [
                        'sts:GetCallerIdentity',
                        # ECS - is the portal up, how many tasks, why did one die
                        'ecs:DescribeClusters', 'ecs:DescribeServices', 'ecs:DescribeTasks',
                        'ecs:DescribeTaskDefinition', 'ecs:DescribeContainerInstances',
                        'ecs:ListClusters', 'ecs:ListServices', 'ecs:ListTasks',
                        'ecs:ListTaskDefinitions', 'ecs:ListContainerInstances',
                        # Load balancing - are the target groups healthy
                        'elasticloadbalancing:DescribeLoadBalancers',
                        'elasticloadbalancing:DescribeTargetGroups',
                        'elasticloadbalancing:DescribeTargetHealth',
                        'elasticloadbalancing:DescribeListeners',
                        'elasticloadbalancing:DescribeRules',
                        'application-autoscaling:DescribeScalableTargets',
                        'application-autoscaling:DescribeScalingPolicies',
                        # Metrics and alarms - saturation, cluster health
                        'cloudwatch:DescribeAlarms', 'cloudwatch:GetMetricData',
                        'cloudwatch:GetMetricStatistics', 'cloudwatch:ListMetrics',
                        # Log group discovery (reading the events themselves is scoped below)
                        'logs:DescribeLogGroups', 'logs:DescribeLogStreams',
                        'logs:DescribeQueries', 'logs:StopQuery',
                        # Datastores
                        'rds:DescribeDBInstances', 'rds:DescribeDBParameters',
                        'rds:DescribeDBSnapshots', 'rds:DescribeEvents',
                        'es:DescribeDomain', 'es:DescribeDomains', 'es:ListDomainNames',
                        'elasticache:DescribeCacheClusters',
                        'sqs:ListQueues',
                        # Deployment provenance - which image is running, did the deploy work
                        'cloudformation:DescribeStacks', 'cloudformation:DescribeStackEvents',
                        'cloudformation:DescribeStackResources', 'cloudformation:ListStacks',
                        'cloudformation:GetTemplate', 'cloudformation:GetStackPolicy',
                        'ecr:GetAuthorizationToken',
                        'codebuild:ListProjects', 'codebuild:ListBuilds',
                        'states:ListStateMachines', 'states:ListExecutions',
                        'lambda:ListFunctions',
                        'ec2:DescribeSecurityGroups', 'ec2:DescribeSubnets', 'ec2:DescribeVpcs',
                        'ec2:DescribeNetworkInterfaces', 'ec2:DescribeAvailabilityZones',
                        'servicequotas:GetServiceQuota', 'servicequotas:ListServiceQuotas',
                        'tag:GetResources',
                        'secretsmanager:ListSecrets',
                        # Key metadata only - no key material, no ciphertext, no key policy.
                        'kms:ListAliases',
                    ],
                    'Resource': '*',
                    'Condition': cls._region_pin(),
                }],
            },
        ))

    def human_diagnose_resource_read_policy(self) -> Policy:
        """ The read/inspection actions that DO support resource-level authorization, scoped to the
            service rather than to enumerated identifiers.

            Secrets Manager and S3 object reads are retained on purpose - a developer is expected
            to inspect the system and bring evidence - and are scoped to this account's secrets and
            buckets. The action lists stay short: reads only, no writes anywhere.
        """
        statements = [
            {
                'Sid': 'ReadApplicationLogs',
                'Effect': 'Allow',
                'Action': [
                    'logs:FilterLogEvents', 'logs:GetLogEvents', 'logs:GetLogGroupFields',
                    'logs:GetLogRecord', 'logs:StartQuery',
                    'logs:GetQueryResults',
                ],
                'Resource': self._log_group_arns(),
            },
            {
                'Sid': 'InspectBucketConfiguration',
                'Effect': 'Allow',
                'Action': [
                    's3:ListBucket', 's3:GetBucketLocation', 's3:GetBucketVersioning',
                    's3:GetBucketPolicy', 's3:GetBucketPolicyStatus',
                    's3:GetEncryptionConfiguration', 's3:GetLifecycleConfiguration',
                    's3:GetBucketPublicAccessBlock', 's3:GetBucketTagging', 's3:GetBucketCORS',
                ],
                'Resource': 'arn:aws:s3:::*',
                'Condition': {'StringEquals': {'s3:ResourceAccount': AccountId}},
            },
            {
                'Sid': 'ReadObjects',
                'Effect': 'Allow',
                'Action': ['s3:GetObject', 's3:GetObjectVersion', 's3:GetObjectTagging'],
                'Resource': 'arn:aws:s3:::*/*',
                'Condition': {'StringEquals': {'s3:ResourceAccount': AccountId}},
            },
            {
                'Sid': 'ReadSecrets',
                'Effect': 'Allow',
                'Action': [
                    'secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret',
                    'secretsmanager:ListSecretVersionIds', 'secretsmanager:GetResourcePolicy',
                ],
                'Resource': self._service_arn('secretsmanager', 'secret:*'),
            },
            {
                'Sid': 'InspectQueueDepth',
                'Effect': 'Allow',
                # Depth and age only. Message bodies are application data - ReceiveMessage is
                # denied in the guardrail policy below.
                'Action': ['sqs:GetQueueAttributes', 'sqs:GetQueueUrl'],
                'Resource': self._service_arn('sqs', '*'),
            },
            {
                'Sid': 'InspectContainerImages',
                'Effect': 'Allow',
                'Action': [
                    'ecr:DescribeRepositories', 'ecr:DescribeImages', 'ecr:ListImages',
                    'ecr:BatchGetImage', 'ecr:GetRepositoryPolicy', 'ecr:GetLifecyclePolicy',
                ],
                'Resource': self._service_arn('ecr', 'repository/*'),
            },
            {
                'Sid': 'InspectBuildsAndWorkflows',
                'Effect': 'Allow',
                'Action': ['codebuild:BatchGetBuilds', 'codebuild:BatchGetProjects'],
                'Resource': self._service_arn('codebuild', 'project/*'),
            },
            {
                'Sid': 'InspectWorkflowExecutions',
                'Effect': 'Allow',
                'Action': ['states:DescribeStateMachine', 'states:DescribeExecution',
                           'states:GetExecutionHistory'],
                'Resource': self._service_arn('states', '*'),
            },
            {
                'Sid': 'InspectKeyMetadata',
                'Effect': 'Allow',
                # Metadata only: no key material, no ciphertext, no key policy.
                'Action': ['kms:DescribeKey', 'kms:GetKeyRotationStatus'],
                'Resource': self._service_arn('kms', 'key/*'),
            },
            {
                'Sid': 'InspectAccountRoleDefinitions',
                'Effect': 'Allow',
                'Action': ['iam:GetRole', 'iam:GetRolePolicy', 'iam:ListRolePolicies',
                           'iam:ListAttachedRolePolicies'],
                'Resource': Join(':', ['arn', 'aws', 'iam', '', AccountId, 'role/*']),
            },
        ]
        if self._human_access_flag(Settings.HUMAN_ACCESS_DIAGNOSE_ALLOW_KMS_DECRYPT):
            # Off by default. Needed to read objects in an SSE-KMS bucket, and at service scope
            # that means any key in the account - hence its own explicit switch. Key policies may
            # already delegate authorization to account IAM policies; enabling this can therefore
            # grant decrypt immediately, without naming this role in a separate key-policy edit.
            statements.append({
                'Sid': 'DecryptWithApplicationKeys',
                'Effect': 'Allow',
                'Action': ['kms:Decrypt', 'kms:GetKeyPolicy'],
                'Resource': self._service_arn('kms', 'key/*'),
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
            # Queue depth comes from GetQueueAttributes; message bodies are application data, and
            # ChangeMessageVisibility is a remediation action rather than a read.
            'sqs:ReceiveMessage', 'sqs:SendMessage', 'sqs:DeleteMessage', 'sqs:PurgeQueue',
            'sqs:ChangeMessageVisibility',
            # Block direct function/configuration retrieval. This is not an information-flow
            # guarantee: ListFunctions, logs and secrets can also expose configuration or data.
            'lambda:GetFunction', 'lambda:GetFunctionConfiguration', 'lambda:InvokeFunction',
            'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration',
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
            actions += ['kms:Decrypt', 'kms:GenerateDataKey',
                        'kms:GenerateDataKeyWithoutPlaintext', 'kms:ReEncryptFrom']
        return Policy(
            PolicyName='HumanDiagnoseGuardrailPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {'Sid': 'DiagnosisIsReadOnly', 'Effect': 'Deny',
                     'Action': actions, 'Resource': '*'},
                    cls.human_access_region_deny_statement(),
                    cls.human_access_s3_account_deny_statement(),
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
        """ Reads needed to target remediation. The same resource splitting and region/account
            conditions as the diagnostic observability policy apply.

            Deliberately narrower than the diagnostic role's reads: no secrets, no S3, no KMS, no
            service quotas, no tag inventory. That keeps CloudTrail cleanly separable into
            "someone was looking" and "someone was changing".
        """
        return cls._scope_inspection_policy(Policy(
            PolicyName='HumanRemediateReadPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Sid': 'ReadsNeededToTargetARemediation',
                    'Effect': 'Allow',
                    'Action': [
                        'sts:GetCallerIdentity',
                        'ecs:DescribeClusters', 'ecs:DescribeServices', 'ecs:DescribeTasks',
                        'ecs:DescribeTaskDefinition', 'ecs:ListClusters', 'ecs:ListServices',
                        'ecs:ListTasks',
                        'elasticloadbalancing:DescribeLoadBalancers',
                        'elasticloadbalancing:DescribeTargetGroups',
                        'elasticloadbalancing:DescribeTargetHealth',
                        'cloudwatch:DescribeAlarms', 'cloudwatch:GetMetricData',
                        'logs:DescribeLogGroups', 'logs:DescribeLogStreams',
                        'sqs:ListQueues',
                        'codebuild:ListProjects', 'codebuild:ListBuilds',
                        'states:ListStateMachines', 'states:ListExecutions',
                        'cloudformation:DescribeStacks', 'cloudformation:ListStacks',
                        'rds:DescribeDBInstances', 'es:DescribeDomain', 'es:ListDomainNames',
                    ],
                    'Resource': '*',
                    'Condition': cls._region_pin(),
                }],
            },
        ))

    @classmethod
    def human_remediate_action_policy(cls) -> Policy:
        """ Operational actions scoped to the service and region, after MFA-protected assumption.
            Direct code-authoring APIs, IAM administration and queue deletion/purge are excluded.
            This is NOT a reversible-only or no-code-execution sandbox: CodeBuild overrides and
            workflow inputs can delegate code/data mutations to existing, separately privileged
            service roles. Keep those explicitly accepted risks visible in operator documentation.
        """
        condition = cls._human_access_mutation_condition()
        return Policy(
            PolicyName='HumanRemediateActionPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        # Restart (force-new-deployment) or rescale (desired-count) a service.
                        'Sid': 'RestartOrRescaleServices',
                        'Effect': 'Allow',
                        'Action': ['ecs:UpdateService'],
                        'Resource': cls._service_arn('ecs', 'service/*'),
                        'Condition': condition,
                    },
                    {
                        # Kill one stuck task; the service replaces it.
                        'Sid': 'StopStuckTasks',
                        'Effect': 'Allow',
                        'Action': ['ecs:StopTask'],
                        'Resource': cls._service_arn('ecs', 'task/*'),
                        'Condition': condition,
                    },
                    {
                        # Release in-flight messages back to the queue. Reversible: nothing is
                        # destroyed, the messages simply become visible again.
                        'Sid': 'ReleaseInFlightQueueMessages',
                        'Effect': 'Allow',
                        'Action': ['sqs:ChangeMessageVisibility'],
                        'Resource': cls._service_arn('sqs', '*'),
                        'Condition': condition,
                    },
                    {
                        # Rerun a stuck workflow.
                        'Sid': 'StartWorkflowExecutions',
                        'Effect': 'Allow',
                        'Action': ['states:StartExecution'],
                        'Resource': cls._service_arn('states', 'stateMachine:*'),
                        'Condition': condition,
                    },
                    {
                        'Sid': 'StopWorkflowExecutions',
                        'Effect': 'Allow',
                        'Action': ['states:StopExecution'],
                        'Resource': cls._service_arn('states', 'execution:*'),
                        'Condition': condition,
                    },
                    {
                        # Deliberately retained delegated execution: StartBuild accepts buildspec,
                        # source, image and environment overrides under the project's service role.
                        # The human boundary does NOT constrain that role. RetryBuild can repeat
                        # an earlier overridden build. See the operator risk/enablement checklist.
                        'Sid': 'DelegateBuildsToExistingServiceRoles',
                        'Effect': 'Allow',
                        'Action': ['codebuild:StartBuild', 'codebuild:StopBuild',
                                   'codebuild:RetryBuild'],
                        'Resource': cls._service_arn('codebuild', 'project/*'),
                        'Condition': condition,
                    },
                ],
            },
        )

    @classmethod
    def human_remediate_guardrail_policy(cls) -> Policy:
        """ Direct API denies: no code-authoring API, queue deletion, secret reads or role chaining.
            These do not constrain downstream execution under CodeBuild or workflow service roles.
        """
        return Policy(
            PolicyName='HumanRemediateGuardrailPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        'Sid': 'DenyDirectCodeDataAndIdentityOperations',
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
                            # Irreversible queue operations are excluded from remediation.
                            'sqs:PurgeQueue', 'sqs:DeleteQueue',
                            'sqs:ReceiveMessage', 'sqs:SendMessage', 'sqs:DeleteMessage',
                            's3:GetObject', 's3:GetObjectVersion', 's3:PutObject',
                            's3:DeleteObject',
                            'secretsmanager:GetSecretValue',
                            'kms:Decrypt', 'kms:GenerateDataKey',
                            'kms:GenerateDataKeyWithoutPlaintext', 'kms:ReEncryptFrom',
                            'ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath',
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
        return Role(
            self.REMEDIATE_ROLE,
            Description='Scoped remediation access for power users. Opt-in; see'
                        ' human_access.* in template.config.json.',
            AssumeRolePolicyDocument=self.human_access_trust_policy(principal_arns),
            MaxSessionDuration=self.HUMAN_ACCESS_REMEDIATE_SESSION_DURATION,
            PermissionsBoundary=Ref(boundary),
            Policies=[
                self.human_remediate_read_policy(),
                self.human_remediate_action_policy(),
                self.human_remediate_guardrail_policy(),
            ],
        )

    # -------------------------------------------------------------------------------------------
    # Opt-in deployment role (human_access.deploy.*)
    #
    # Deploys this repository's CloudFormation stacks through reviewed change sets: the template
    # files `cli provision` writes, and the Foursight package `cli provision foursight*` builds.
    # It is a separate trust decision from diagnosis/remediation, so it has its own enable flag
    # and principal list and never shares their permission boundary.
    #
    # Scope model. As for the other human roles the account is assumed to hold only our own
    # resources, so resource-authorized actions are scoped to account/region service ARNs. Two
    # places narrow further because the CLI's naming makes it possible:
    #   * CloudFormation writes are limited to stacks named COMMON_STACK_PREFIX ('c4-'), and
    #   * IAM writes are limited to roles/users/instance profiles whose generated names start
    #     with that prefix (every template here lets CloudFormation generate IAM names).
    #
    # This is NOT a low-privilege role. Deploying this system means creating IAM roles with
    # inline policies and handing them to ECS, Lambda, CodeBuild and EC2, so whoever can deploy can
    # obtain any permission those runtime roles can be given. The guardrails below stop direct
    # self-escalation (editing this role, the other human-access roles, DevRole, or their
    # policies), identity/org/billing administration, running workloads directly, destroying
    # data-bearing resources and overwriting the filled application configuration secret.
    # -------------------------------------------------------------------------------------------

    # Discovery/inspection and the few writes that have no resource-level authorization.
    DEPLOY_WILDCARD_SIDS = (
        'InspectStacksAndDeploymentTargets',
        'ActionsWithoutResourceLevelAuthorization',
    )

    # The only AWS managed policies any role this role may manage attaches (the CodeBuild service
    # roles). DevRole's ten are deliberately absent: DevRole is protected from this role entirely.
    DEPLOY_ATTACHABLE_MANAGED_POLICIES = (
        'arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess',
        'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser',
        'arn:aws:iam::aws:policy/AmazonS3FullAccess',
        'arn:aws:iam::aws:policy/CloudWatchFullAccess',
    )

    # Services that the generated runtime roles are handed to: ECS task/execution roles, CodeBuild
    # service roles, the ECS instance profile, and the Foursight Lambda role.
    DEPLOY_PASS_ROLE_SERVICES = (
        'codebuild.amazonaws.com',
        'ec2.amazonaws.com',
        'ecs-tasks.amazonaws.com',
        'lambda.amazonaws.com',
    )

    # Service-linked roles the services in these templates create on first use.
    DEPLOY_SERVICE_LINKED_ROLE_SERVICES = (
        'ecs.amazonaws.com',
        'elasticache.amazonaws.com',
        'elasticloadbalancing.amazonaws.com',
        'es.amazonaws.com',
        'opensearchservice.amazonaws.com',
        'rds.amazonaws.com',
    )

    # Resource-name patterns this role must never modify or pass: itself, the other human-access
    # roles, the account-root-trusted DevRole, and their policies. Matched anywhere in the
    # CloudFormation-generated name (<stack>-<LogicalId>-<suffix>), whatever the app prefix.
    DEPLOY_PROTECTED_IAM_PATTERNS = (
        'role/*DevDiagnoseRole*',
        'role/*PowerRemediateRole*',
        'role/*InfraDeployRole*',
        'role/*DevRole*',
        'policy/*HumanAccessBoundary*',
        'policy/*InfraDeploy*',
    )

    # Physical-name patterns. Every stack this CLI provisions is named COMMON_STACK_PREFIX + ...,
    # and CloudFormation-generated IAM names begin with the stack name.
    DEPLOY_NAME_PATTERN = COMMON_STACK_PREFIX + '*'
    # Foursight/application package buckets are '<...>-application-versions' (FSBucketTemplate).
    DEPLOY_ARTIFACT_BUCKET_PATTERN = '*application-versions'
    # Application configuration (GAC) secrets that operators fill in after creation.
    DEPLOY_FILLED_SECRET_PATTERN = 'C4AppConfig*'
    # The RDS secret whose host/port SecretTargetAttachment writes.
    DEPLOY_RDS_SECRET_PATTERN = 'C4*RDSSecret*'

    # IAM role names are at most 64 characters; CloudFormation generates <stack>-<LogicalId>-<suffix>
    # and shortens it when too long. Allow 13 characters for '-' plus the random suffix.
    _IAM_ROLE_NAME_LIMIT = 64
    _GENERATED_SUFFIX_ALLOWANCE = 13

    @classmethod
    def check_protected_names_fit(cls, stack_name: str) -> None:
        """ The guardrail recognises the human-access roles and DevRole by their logical-id token
            inside the generated name. Refuse to synthesize the deploy role if this IAM stack's
            name is long enough that a generated name could be shortened and lose that token.
        """
        # Longest protected logical id across all apps ('SMaHTPowerRemediateRole').
        longest = max(len(app + token) for app in ('CGAP', 'FF', 'SMaHT')
                      for token in ('DevDiagnoseRole', 'PowerRemediateRole', 'InfraDeployRole', 'DevRole'))
        if len(stack_name) + 1 + longest + cls._GENERATED_SUFFIX_ALLOWANCE > cls._IAM_ROLE_NAME_LIMIT:
            raise ValueError(f'IAM stack name {stack_name!r} is too long for the deploy role guardrail to'
                             f' recognise generated role names reliably; use a shorter ecosystem name.')

    @staticmethod
    def _iam_arn(suffix: str):
        return Join(':', ['arn', 'aws', 'iam', '', AccountId, suffix])

    @classmethod
    def _deploy_region_pin(cls) -> dict:
        return cls._region_pin()

    @classmethod
    def human_deploy_stack_policy(cls) -> dict:
        """ CloudFormation change sets, the reads needed to synthesize/review them, and IAM for
            the generated runtime identities.
        """
        prefix = cls.DEPLOY_NAME_PATTERN
        return {
            'Version': '2012-10-17',
            'Statement': [
                {
                    # Synthesis reads stack outputs (ConfigManager.find_stack_output); the AWS CLI
                    # deploy/package commands describe stacks and wait on change sets; the
                    # resource handlers below need these describes. Read-only, region-pinned.
                    'Sid': 'InspectStacksAndDeploymentTargets',
                    'Effect': 'Allow',
                    'Action': [
                        'sts:GetCallerIdentity',
                        'cloudformation:DescribeStacks', 'cloudformation:DescribeStackEvents',
                        'cloudformation:DescribeStackResource',
                        'cloudformation:DescribeStackResources', 'cloudformation:ListStacks',
                        'cloudformation:ListStackResources', 'cloudformation:ListExports',
                        'cloudformation:ListImports', 'cloudformation:GetTemplate',
                        'cloudformation:GetTemplateSummary', 'cloudformation:ValidateTemplate',
                        'cloudformation:DescribeChangeSet', 'cloudformation:ListChangeSets',
                        'ec2:DescribeAccountAttributes', 'ec2:DescribeAddresses',
                        'ec2:DescribeAvailabilityZones', 'ec2:DescribeImages',
                        'ec2:DescribeInstanceAttribute', 'ec2:DescribeInstanceCreditSpecifications',
                        'ec2:DescribeInstances', 'ec2:DescribeInternetGateways',
                        'ec2:DescribeKeyPairs', 'ec2:DescribeLaunchTemplates',
                        'ec2:DescribeNatGateways', 'ec2:DescribeNetworkAcls',
                        'ec2:DescribeNetworkInterfaces', 'ec2:DescribeRouteTables',
                        'ec2:DescribeSecurityGroupRules', 'ec2:DescribeSecurityGroups',
                        'ec2:DescribeSubnets', 'ec2:DescribeVolumes', 'ec2:DescribeVpcAttribute',
                        'ec2:DescribeVpcEndpoints', 'ec2:DescribeVpcs',
                        'elasticloadbalancing:DescribeListenerAttributes',
                        'elasticloadbalancing:DescribeListeners',
                        'elasticloadbalancing:DescribeLoadBalancerAttributes',
                        'elasticloadbalancing:DescribeLoadBalancers',
                        'elasticloadbalancing:DescribeTags',
                        'elasticloadbalancing:DescribeTargetGroupAttributes',
                        'elasticloadbalancing:DescribeTargetGroups',
                        'elasticloadbalancing:DescribeTargetHealth',
                        'ecs:DescribeTaskDefinition', 'codebuild:ListProjects',
                        'rds:DescribeDBEngineVersions', 'rds:DescribeEngineDefaultParameters',
                        'rds:DescribeEvents',
                        'logs:DescribeLogGroups', 'logs:DescribeResourcePolicies',
                        'logs:DescribeIndexPolicies',
                        'cloudwatch:DescribeAlarms',
                    ],
                    'Resource': '*',
                    'Condition': cls._deploy_region_pin(),
                },
                {
                    # Actions these services authorize only against '*'. Each is needed by a
                    # resource type in the templates (datastore KMS key, RDS secret password,
                    # CodeBuild GitHub source credential, ECS task definitions) or by the image
                    # push path (`aws ecr get-login-password` / `docker login`).
                    'Sid': 'ActionsWithoutResourceLevelAuthorization',
                    'Effect': 'Allow',
                    'Action': [
                        'kms:CreateKey', 'kms:TagResource',
                        'secretsmanager:GetRandomPassword',
                        'codebuild:ImportSourceCredentials', 'codebuild:ListSourceCredentials',
                        'codebuild:DeleteSourceCredentials',
                        'ecs:RegisterTaskDefinition', 'ecs:DeregisterTaskDefinition',
                        'ecr:GetAuthorizationToken',
                    ],
                    'Resource': '*',
                    'Condition': cls._deploy_region_pin(),
                },
                {
                    # Change sets only - the reviewed path `aws cloudformation deploy
                    # --no-execute-changeset` uses. Passing a CloudFormation service role is
                    # refused: this role's own permissions are the whole authority.
                    'Sid': 'CreateChangeSetsForC4Stacks',
                    'Effect': 'Allow',
                    'Action': ['cloudformation:CreateChangeSet'],
                    'Resource': [
                        cls._service_arn('cloudformation', f'stack/{prefix}/*'),
                        Join(':', ['arn', 'aws', 'cloudformation', Region, 'aws',
                                   'transform/Serverless-2016-10-31']),
                    ],
                    'Condition': {
                        'StringEquals': {'aws:RequestedRegion': Region},
                        'Null': {'cloudformation:RoleArn': 'true'},
                    },
                },
                {
                    'Sid': 'ExecuteOrAbandonReviewedChangeSets',
                    'Effect': 'Allow',
                    'Action': [
                        'cloudformation:ExecuteChangeSet', 'cloudformation:DeleteChangeSet',
                        'cloudformation:CancelUpdateStack',
                    ],
                    'Resource': cls._service_arn('cloudformation', f'stack/{prefix}/*'),
                    'Condition': cls._deploy_region_pin(),
                },
                {
                    # Recovery and cleanup of c4-* stacks: finish or force a rollback, and delete
                    # a stack (including a ROLLBACK_COMPLETE first create, which must be deleted
                    # before a retry). CloudFormation then deletes each resource with this role's
                    # session, so the guardrail's data-bearing deletion denies still apply:
                    # those resources fail to delete and must be retained (--retain-resources).
                    'Sid': 'RecoverOrDeleteC4Stacks',
                    'Effect': 'Allow',
                    'Action': [
                        'cloudformation:ContinueUpdateRollback', 'cloudformation:RollbackStack',
                        'cloudformation:DeleteStack',
                    ],
                    'Resource': cls._service_arn('cloudformation', f'stack/{prefix}/*'),
                    'Condition': {
                        'StringEquals': {'aws:RequestedRegion': Region},
                        'Null': {'cloudformation:RoleArn': 'true'},
                    },
                },
                {
                    # The runtime identities the templates define. Names are generated by
                    # CloudFormation from the stack name, hence the prefix.
                    'Sid': 'ManageGeneratedRuntimeIdentities',
                    'Effect': 'Allow',
                    'Action': [
                        'iam:CreateRole', 'iam:DeleteRole', 'iam:GetRole', 'iam:UpdateRole',
                        'iam:UpdateRoleDescription', 'iam:UpdateAssumeRolePolicy',
                        'iam:PutRolePolicy', 'iam:DeleteRolePolicy', 'iam:GetRolePolicy',
                        'iam:ListRolePolicies', 'iam:ListAttachedRolePolicies', 'iam:TagRole',
                        'iam:UntagRole',
                        'iam:CreateInstanceProfile', 'iam:DeleteInstanceProfile',
                        'iam:GetInstanceProfile', 'iam:AddRoleToInstanceProfile',
                        'iam:RemoveRoleFromInstanceProfile',
                        'iam:CreateUser', 'iam:DeleteUser', 'iam:GetUser', 'iam:PutUserPolicy',
                        'iam:DeleteUserPolicy', 'iam:GetUserPolicy', 'iam:ListUserPolicies',
                        'iam:ListAttachedUserPolicies', 'iam:ListGroupsForUser',
                        'iam:ListAccessKeys', 'iam:GetLoginProfile', 'iam:TagUser',
                        'iam:UntagUser',
                    ],
                    'Resource': [cls._iam_arn(f'role/{prefix}'), cls._iam_arn(f'user/{prefix}'),
                                 cls._iam_arn(f'instance-profile/{prefix}')],
                },
                {
                    'Sid': 'AttachOnlyTheManagedPoliciesTheTemplatesUse',
                    'Effect': 'Allow',
                    'Action': ['iam:AttachRolePolicy', 'iam:DetachRolePolicy'],
                    'Resource': cls._iam_arn(f'role/{prefix}'),
                    'Condition': {'ArnEquals': {
                        'iam:PolicyARN': list(cls.DEPLOY_ATTACHABLE_MANAGED_POLICIES)}},
                },
                {
                    # IfExists: some PassRole checks (for example adding a role to an instance
                    # profile) carry no service; where AWS supplies it, it must be one of these.
                    'Sid': 'PassGeneratedRolesToTheServicesThatRunThem',
                    'Effect': 'Allow',
                    'Action': ['iam:PassRole'],
                    'Resource': cls._iam_arn(f'role/{prefix}'),
                    'Condition': {'StringEqualsIfExists': {
                        'iam:PassedToService': list(cls.DEPLOY_PASS_ROLE_SERVICES)}},
                },
                {
                    'Sid': 'CreateRequiredServiceLinkedRoles',
                    'Effect': 'Allow',
                    'Action': ['iam:CreateServiceLinkedRole'],
                    'Resource': cls._iam_arn('role/aws-service-role/*'),
                    'Condition': {'StringEquals': {
                        'iam:AWSServiceName': list(cls.DEPLOY_SERVICE_LINKED_ROLE_SERVICES)}},
                },
            ],
        }

    @classmethod
    def human_deploy_compute_policy(cls) -> dict:
        """ Network, instances, load balancing, ECS, logs/alarms and the Foursight serverless
            resources (Lambda, EventBridge schedules, API Gateway).
        """
        return {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Sid': 'ManageNetworkSecurityGroupsAndInstances',
                    'Effect': 'Allow',
                    'Action': [
                        'ec2:CreateVpc', 'ec2:DeleteVpc', 'ec2:ModifyVpcAttribute',
                        'ec2:CreateSubnet', 'ec2:DeleteSubnet', 'ec2:ModifySubnetAttribute',
                        'ec2:CreateInternetGateway', 'ec2:DeleteInternetGateway',
                        'ec2:AttachInternetGateway', 'ec2:DetachInternetGateway',
                        'ec2:AllocateAddress', 'ec2:ReleaseAddress', 'ec2:AssociateAddress',
                        'ec2:DisassociateAddress',
                        'ec2:CreateNatGateway', 'ec2:DeleteNatGateway',
                        'ec2:CreateRouteTable', 'ec2:DeleteRouteTable', 'ec2:CreateRoute',
                        'ec2:ReplaceRoute', 'ec2:DeleteRoute', 'ec2:AssociateRouteTable',
                        'ec2:DisassociateRouteTable', 'ec2:ReplaceRouteTableAssociation',
                        'ec2:CreateSecurityGroup', 'ec2:DeleteSecurityGroup',
                        'ec2:AuthorizeSecurityGroupIngress', 'ec2:AuthorizeSecurityGroupEgress',
                        'ec2:RevokeSecurityGroupIngress', 'ec2:RevokeSecurityGroupEgress',
                        'ec2:UpdateSecurityGroupRuleDescriptionsIngress',
                        'ec2:UpdateSecurityGroupRuleDescriptionsEgress',
                        'ec2:CreateVpcEndpoint', 'ec2:ModifyVpcEndpoint',
                        'ec2:DeleteVpcEndpoints',
                        'ec2:CreateTags', 'ec2:DeleteTags',
                        'ec2:RunInstances', 'ec2:StartInstances', 'ec2:StopInstances',
                        'ec2:TerminateInstances', 'ec2:ModifyInstanceAttribute',
                    ],
                    # Images carry no account in their ARN (shared AMIs are permitted).
                    'Resource': [cls._service_arn('ec2', '*'),
                                 Join(':', ['arn', 'aws', 'ec2', Region, '', 'image/*'])],
                },
                {
                    'Sid': 'ManageLoadBalancing',
                    'Effect': 'Allow',
                    'Action': [
                        'elasticloadbalancing:CreateLoadBalancer',
                        'elasticloadbalancing:DeleteLoadBalancer',
                        'elasticloadbalancing:ModifyLoadBalancerAttributes',
                        'elasticloadbalancing:SetSecurityGroups', 'elasticloadbalancing:SetSubnets',
                        'elasticloadbalancing:SetIpAddressType',
                        'elasticloadbalancing:CreateTargetGroup',
                        'elasticloadbalancing:DeleteTargetGroup',
                        'elasticloadbalancing:ModifyTargetGroup',
                        'elasticloadbalancing:ModifyTargetGroupAttributes',
                        'elasticloadbalancing:RegisterTargets',
                        'elasticloadbalancing:DeregisterTargets',
                        'elasticloadbalancing:CreateListener', 'elasticloadbalancing:DeleteListener',
                        'elasticloadbalancing:ModifyListener',
                        'elasticloadbalancing:ModifyListenerAttributes',
                        'elasticloadbalancing:AddTags', 'elasticloadbalancing:RemoveTags',
                    ],
                    'Resource': cls._service_arn('elasticloadbalancing', '*'),
                },
                {
                    'Sid': 'ManageContainerServices',
                    'Effect': 'Allow',
                    'Action': [
                        'ecs:CreateCluster', 'ecs:DeleteCluster', 'ecs:UpdateCluster',
                        'ecs:UpdateClusterSettings', 'ecs:PutClusterCapacityProviders',
                        'ecs:DescribeClusters', 'ecs:CreateService', 'ecs:UpdateService',
                        'ecs:DeleteService', 'ecs:DescribeServices',
                        'ecs:DescribeServiceDeployments', 'ecs:ListServiceDeployments',
                        'ecs:StopServiceDeployment',
                        'ecs:TagResource', 'ecs:UntagResource', 'ecs:ListTagsForResource',
                    ],
                    'Resource': cls._service_arn('ecs', '*'),
                },
                {
                    # The CodeBuild projects (portal, pipeline and Tibanna image builders) are
                    # started from the console or `aws codebuild start-build`, and watched or
                    # stopped. A build runs as the project's service role; see the docs for what
                    # that delegates. Per-build overrides are not restricted. RetryBuild and
                    # batch builds are not granted: StartBuild covers a re-run.
                    'Sid': 'StartWatchAndStopImageBuilds',
                    'Effect': 'Allow',
                    'Action': ['codebuild:StartBuild', 'codebuild:StopBuild',
                               'codebuild:BatchGetBuilds', 'codebuild:ListBuildsForProject'],
                    'Resource': cls._service_arn('codebuild', 'project/*'),
                },
                {
                    # `docker push` (AWS's documented push permissions) and the add-image-tag /
                    # unrelease-most-recent-image retag commands (DescribeImages, BatchGetImage,
                    # PutImage). Image deletion stays denied.
                    'Sid': 'PushAndRetagImages',
                    'Effect': 'Allow',
                    'Action': [
                        'ecr:BatchCheckLayerAvailability', 'ecr:InitiateLayerUpload',
                        'ecr:UploadLayerPart', 'ecr:CompleteLayerUpload', 'ecr:PutImage',
                        'ecr:BatchGetImage', 'ecr:DescribeImages',
                    ],
                    'Resource': cls._service_arn('ecr', 'repository/*'),
                },
                {
                    'Sid': 'ManageLogGroupsAndAlarms',
                    'Effect': 'Allow',
                    'Action': [
                        'logs:CreateLogGroup', 'logs:PutRetentionPolicy',
                        'logs:DeleteRetentionPolicy', 'logs:GetDataProtectionPolicy',
                        'logs:TagResource', 'logs:UntagResource', 'logs:ListTagsForResource',
                        'cloudwatch:PutMetricAlarm', 'cloudwatch:DeleteAlarms',
                        'cloudwatch:TagResource', 'cloudwatch:UntagResource',
                        'cloudwatch:ListTagsForResource',
                    ],
                    'Resource': [cls._service_arn('logs', 'log-group:*'),
                                 cls._service_arn('cloudwatch', 'alarm:*')],
                },
                {
                    'Sid': 'ManageFoursightFunctionsAndSchedules',
                    'Effect': 'Allow',
                    'Action': [
                        'lambda:CreateFunction', 'lambda:DeleteFunction', 'lambda:GetFunction',
                        'lambda:UpdateFunctionCode', 'lambda:UpdateFunctionConfiguration',
                        'lambda:GetFunctionCodeSigningConfig', 'lambda:GetRuntimeManagementConfig',
                        'lambda:GetFunctionRecursionConfig', 'lambda:GetFunctionScalingConfig',
                        'lambda:AddPermission', 'lambda:RemovePermission', 'lambda:GetPolicy',
                        'lambda:TagResource', 'lambda:UntagResource',
                        'events:PutRule', 'events:DeleteRule', 'events:DescribeRule',
                        'events:PutTargets', 'events:RemoveTargets', 'events:ListTargetsByRule',
                        'events:TagResource', 'events:UntagResource',
                        'events:ListTagsForResource',
                    ],
                    'Resource': [cls._service_arn('lambda', 'function:*'),
                                 cls._service_arn('events', 'rule/*')],
                },
                {
                    # Chalice attaches a published layer from another account; reading its
                    # version is required to create the function.
                    'Sid': 'ReadPublishedLambdaLayers',
                    'Effect': 'Allow',
                    'Action': ['lambda:GetLayerVersion'],
                    'Resource': Join(':', ['arn', 'aws', 'lambda', Region, '*', 'layer', '*', '*']),
                },
                {
                    'Sid': 'ManageFoursightRestApi',
                    'Effect': 'Allow',
                    'Action': ['apigateway:GET', 'apigateway:POST', 'apigateway:PUT',
                               'apigateway:PATCH', 'apigateway:DELETE',
                               'apigateway:UpdateRestApiPolicy'],
                    'Resource': [Join('', ['arn:aws:apigateway:', Region, '::/restapis']),
                                 Join('', ['arn:aws:apigateway:', Region, '::/restapis/*']),
                                 Join('', ['arn:aws:apigateway:', Region, '::/tags/*'])],
                },
            ],
        }

    @classmethod
    def human_deploy_data_policy(cls) -> dict:
        """ Datastores, queues, buckets, registries and build projects - create and update only;
            the deletes that would destroy their data are denied in the guardrail policy - plus
            the datastore keys, application secrets and packaged-artifact uploads.
        """
        return {
            'Version': '2012-10-17',
            'Statement': [
                {
                    'Sid': 'ManageDatabases',
                    'Effect': 'Allow',
                    'Action': [
                        'rds:CreateDBInstance', 'rds:ModifyDBInstance', 'rds:RebootDBInstance',
                        'rds:DescribeDBInstances', 'rds:DescribeDBClusters',
                        'rds:DescribeDBSnapshots', 'rds:DescribeDBClusterSnapshots',
                        'rds:DescribeDBInstanceAutomatedBackups',
                        'rds:CreateDBParameterGroup', 'rds:ModifyDBParameterGroup',
                        'rds:ResetDBParameterGroup', 'rds:DeleteDBParameterGroup',
                        'rds:DescribeDBParameterGroups', 'rds:DescribeDBParameters',
                        'rds:CreateDBSubnetGroup', 'rds:ModifyDBSubnetGroup',
                        'rds:DeleteDBSubnetGroup', 'rds:DescribeDBSubnetGroups',
                        'rds:AddTagsToResource', 'rds:RemoveTagsFromResource',
                        'rds:ListTagsForResource',
                    ],
                    'Resource': cls._service_arn('rds', '*'),
                },
                {
                    # OpenSearchService::Domain (datastore) and the legacy Elasticsearch::Domain
                    # (datastore_slim). Index/document HTTP APIs are denied.
                    'Sid': 'ManageSearchDomains',
                    'Effect': 'Allow',
                    'Action': [
                        'es:CreateDomain', 'es:UpdateDomainConfig', 'es:UpgradeDomain',
                        'es:DescribeDomain', 'es:DescribeDomainConfig',
                        'es:DescribeDomainChangeProgress',
                        'es:CreateElasticsearchDomain', 'es:UpdateElasticsearchDomainConfig',
                        'es:UpgradeElasticsearchDomain', 'es:DescribeElasticsearchDomain',
                        'es:DescribeElasticsearchDomainConfig',
                        'es:AddTags', 'es:RemoveTags', 'es:ListTags',
                    ],
                    'Resource': cls._service_arn('es', 'domain/*'),
                },
                {
                    'Sid': 'ManageCaches',
                    'Effect': 'Allow',
                    'Action': [
                        'elasticache:CreateReplicationGroup', 'elasticache:ModifyReplicationGroup',
                        'elasticache:DescribeReplicationGroups',
                        'elasticache:IncreaseReplicaCount', 'elasticache:DecreaseReplicaCount',
                        'elasticache:CreateCacheCluster', 'elasticache:DeleteCacheCluster',
                        'elasticache:DescribeCacheClusters',
                        'elasticache:CreateCacheSubnetGroup', 'elasticache:ModifyCacheSubnetGroup',
                        'elasticache:DeleteCacheSubnetGroup',
                        'elasticache:DescribeCacheSubnetGroups',
                        'elasticache:AddTagsToResource', 'elasticache:RemoveTagsFromResource',
                        'elasticache:ListTagsForResource',
                    ],
                    'Resource': cls._service_arn('elasticache', '*'),
                },
                {
                    'Sid': 'ManageQueues',
                    'Effect': 'Allow',
                    'Action': ['sqs:CreateQueue', 'sqs:SetQueueAttributes',
                               'sqs:GetQueueAttributes', 'sqs:GetQueueUrl', 'sqs:TagQueue',
                               'sqs:UntagQueue', 'sqs:ListQueueTags'],
                    'Resource': cls._service_arn('sqs', '*'),
                },
                {
                    # Bucket configuration only; object writes are limited to package uploads.
                    'Sid': 'ManageBucketConfiguration',
                    'Effect': 'Allow',
                    'Action': [
                        's3:CreateBucket', 's3:ListBucket', 's3:GetBucketAcl', 's3:PutBucketAcl',
                        's3:GetBucketTagging', 's3:PutBucketTagging',
                        's3:GetBucketVersioning', 's3:PutBucketVersioning',
                        's3:GetLifecycleConfiguration', 's3:PutLifecycleConfiguration',
                        's3:GetEncryptionConfiguration', 's3:PutEncryptionConfiguration',
                        's3:GetBucketPolicy', 's3:PutBucketPolicy', 's3:DeleteBucketPolicy',
                        's3:GetBucketPublicAccessBlock', 's3:PutBucketPublicAccessBlock',
                        's3:GetBucketOwnershipControls', 's3:PutBucketOwnershipControls',
                        's3:GetBucketCORS', 's3:GetBucketLogging', 's3:GetBucketNotification',
                        's3:GetBucketObjectLockConfiguration', 's3:GetBucketWebsite',
                        's3:GetReplicationConfiguration', 's3:GetAccelerateConfiguration',
                        's3:GetAnalyticsConfiguration', 's3:GetIntelligentTieringConfiguration',
                        's3:GetInventoryConfiguration', 's3:GetMetricsConfiguration',
                        's3:GetBucketAbac', 's3:GetBucketMetadataTableConfiguration',
                        's3:ListTagsForResource',
                    ],
                    'Resource': 'arn:aws:s3:::*',
                },
                {
                    'Sid': 'ManageImageRepositories',
                    'Effect': 'Allow',
                    'Action': [
                        'ecr:CreateRepository', 'ecr:DescribeRepositories',
                        'ecr:SetRepositoryPolicy', 'ecr:GetRepositoryPolicy',
                        'ecr:DeleteRepositoryPolicy', 'ecr:PutImageScanningConfiguration',
                        'ecr:GetLifecyclePolicy', 'ecr:TagResource', 'ecr:UntagResource',
                        'ecr:ListTagsForResource',
                    ],
                    'Resource': cls._service_arn('ecr', 'repository/*'),
                },
                {
                    'Sid': 'ManageBuildProjects',
                    'Effect': 'Allow',
                    'Action': ['codebuild:CreateProject', 'codebuild:UpdateProject',
                               'codebuild:DeleteProject', 'codebuild:BatchGetProjects'],
                    'Resource': cls._service_arn('codebuild', 'project/*'),
                },
                {
                    # KMS also requires the key policy to name this role. The datastore key
                    # policy does so when this role is configured (human_deploy_key_policy_
                    # statements); keys created before that need one administrator update.
                    'Sid': 'MaintainDatastoreKeys',
                    'Effect': 'Allow',
                    'Action': [
                        'kms:DescribeKey', 'kms:GetKeyPolicy', 'kms:PutKeyPolicy',
                        'kms:GetKeyRotationStatus', 'kms:ListResourceTags',
                        'kms:UntagResource', 'kms:UpdateKeyDescription',
                    ],
                    'Resource': cls._service_arn('kms', 'key/*'),
                },
                {
                    # SSE-KMS package/template uploads and CloudFormation/Lambda reads of them.
                    'Sid': 'UseKeysOnlyThroughS3',
                    'Effect': 'Allow',
                    'Action': ['kms:GenerateDataKey', 'kms:Decrypt'],
                    'Resource': cls._service_arn('kms', 'key/*'),
                    'Condition': {'StringEquals': {
                        'kms:ViaService': Join('.', ['s3', Region, 'amazonaws.com'])}},
                },
                {
                    'Sid': 'CreateApplicationSecrets',
                    'Effect': 'Allow',
                    'Action': ['secretsmanager:CreateSecret', 'secretsmanager:DescribeSecret',
                               'secretsmanager:TagResource', 'secretsmanager:UntagResource'],
                    'Resource': cls._service_arn('secretsmanager', 'secret:C4*'),
                },
                {
                    # Dynamic references ({{resolve:secretsmanager:...}}) and the Secret resource
                    # handlers read values with the caller's credentials. A deployer can
                    # therefore read these secrets.
                    'Sid': 'ResolveApplicationSecrets',
                    'Effect': 'Allow',
                    'Action': ['secretsmanager:GetSecretValue'],
                    'Resource': cls._service_arn('secretsmanager', 'secret:C4*'),
                },
                {
                    'Sid': 'AttachDatabaseEndpointToItsSecret',
                    'Effect': 'Allow',
                    'Action': ['secretsmanager:PutSecretValue'],
                    'Resource': cls._service_arn('secretsmanager',
                                                 f'secret:{cls.DEPLOY_RDS_SECRET_PATTERN}'),
                },
                {
                    # `aws cloudformation package/deploy --s3-bucket` uploads, and the template/
                    # code reads CloudFormation and Lambda then make with this role's session.
                    'Sid': 'UploadAndReadPackagedArtifacts',
                    'Effect': 'Allow',
                    'Action': ['s3:PutObject', 's3:GetObject', 's3:GetObjectVersion',
                               's3:AbortMultipartUpload'],
                    'Resource': f'arn:aws:s3:::{cls.DEPLOY_ARTIFACT_BUCKET_PATTERN}/*',
                    'Condition': {'StringEquals': {'s3:ResourceAccount': AccountId}},
                },
            ],
        }

    @classmethod
    def human_deploy_guardrail_policy(cls) -> Policy:
        """ Explicit denies. These hold even though the allows above already omit most of these
            actions, so a later broadening of an allow cannot silently remove them.
        """
        protected = [cls._iam_arn(pattern) for pattern in cls.DEPLOY_PROTECTED_IAM_PATTERNS]
        return Policy(
            PolicyName='HumanDeployGuardrailPolicy',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [
                    {
                        # No self-escalation: this role, the other human-access roles, the
                        # account-root-trusted DevRole and their policies are administrator-owned.
                        'Sid': 'NeverModifyHumanAccessIdentities',
                        'Effect': 'Deny',
                        'Action': [
                            'iam:Create*', 'iam:Delete*', 'iam:Update*', 'iam:Put*',
                            'iam:Attach*', 'iam:Detach*', 'iam:Add*', 'iam:Remove*',
                            'iam:Tag*', 'iam:Untag*', 'iam:SetDefaultPolicyVersion',
                            'iam:PassRole',
                        ],
                        'Resource': protected,
                    },
                    {
                        'Sid': 'NeverIdentityCredentialOrgOrBillingAdministration',
                        'Effect': 'Deny',
                        'Action': [
                            'iam:CreateAccessKey', 'iam:UpdateAccessKey', 'iam:CreateLoginProfile',
                            'iam:UpdateLoginProfile', 'iam:CreateServiceSpecificCredential',
                            'iam:UploadSSHPublicKey', 'iam:UploadSigningCertificate',
                            'iam:CreateVirtualMFADevice', 'iam:EnableMFADevice',
                            'iam:DeactivateMFADevice', 'iam:CreateSAMLProvider',
                            'iam:CreateOpenIDConnectProvider', 'iam:UpdateAccountPasswordPolicy',
                            'iam:CreatePolicy', 'iam:CreatePolicyVersion',
                            'iam:SetDefaultPolicyVersion', 'iam:CreateGroup', 'iam:PutGroupPolicy',
                            'iam:AttachGroupPolicy', 'iam:AddUserToGroup', 'iam:AttachUserPolicy',
                            'iam:PutRolePermissionsBoundary', 'iam:DeleteRolePermissionsBoundary',
                            'iam:PutUserPermissionsBoundary', 'iam:DeleteUserPermissionsBoundary',
                            'sso:*', 'sso-directory:*', 'identitystore:*', 'organizations:*',
                            'account:*', 'aws-portal:*', 'billing:*', 'ce:*', 'budgets:*', 'cur:*',
                            'sts:AssumeRole', 'sts:AssumeRoleWithSAML',
                            'sts:AssumeRoleWithWebIdentity', 'sts:GetFederationToken',
                        ],
                        'Resource': '*',
                    },
                    {
                        # Deployment is not workload execution: no direct function invocations,
                        # tasks, shells, workflows or application data-plane access. Image builds
                        # (StartBuild) and image pushes are allowed above as part of the release
                        # workflow; retries, batch builds and image deletion are not.
                        'Sid': 'NeverRunWorkloadsDirectly',
                        'Effect': 'Deny',
                        'Action': [
                            'lambda:InvokeFunction', 'lambda:InvokeFunctionUrl',
                            'ecs:RunTask', 'ecs:StartTask', 'ecs:ExecuteCommand',
                            'codebuild:RetryBuild', 'codebuild:StartBuildBatch',
                            'codebuild:RetryBuildBatch',
                            'states:StartExecution', 'states:StartSyncExecution',
                            'ssm:SendCommand', 'ssm:StartSession',
                            'ec2-instance-connect:SendSSHPublicKey',
                            'ecr:BatchDeleteImage',
                            'es:ESHttp*', 'sqs:SendMessage', 'sqs:ReceiveMessage',
                            'sqs:DeleteMessage',
                        ],
                        'Resource': '*',
                    },
                    {
                        # Data is never destroyed by this role, whether directly, by a change set
                        # that replaces or removes the resource, or by DeleteStack: CloudFormation
                        # calls these with the role's session, so the resource fails to delete
                        # and has to be retained. Removing it is an administrator's job.
                        'Sid': 'NeverDestroyDataBearingResources',
                        'Effect': 'Deny',
                        'Action': [
                            'rds:DeleteDBInstance', 'rds:DeleteDBCluster', 'rds:DeleteDBSnapshot',
                            'rds:DeleteDBClusterSnapshot',
                            'es:DeleteDomain', 'es:DeleteElasticsearchDomain',
                            's3:DeleteBucket', 's3:DeleteObject', 's3:DeleteObjectVersion',
                            'sqs:DeleteQueue', 'sqs:PurgeQueue',
                            'secretsmanager:DeleteSecret',
                            'kms:ScheduleKeyDeletion', 'kms:DisableKey',
                            'ecr:DeleteRepository',
                            'logs:DeleteLogGroup',
                            'elasticache:DeleteReplicationGroup', 'elasticache:DeleteSnapshot',
                        ],
                        'Resource': '*',
                    },
                    {
                        # Stack deletion and rollback only for the c4-* stacks this CLI names;
                        # no stack sets; and administrator-set termination protection and stack
                        # policies cannot be removed by this role.
                        'Sid': 'NeverDeleteOtherStacksOrRemoveStackProtections',
                        'Effect': 'Deny',
                        'Action': ['cloudformation:DeleteStack', 'cloudformation:RollbackStack'],
                        'NotResource': cls._service_arn(
                            'cloudformation', f'stack/{cls.DEPLOY_NAME_PATTERN}/*'),
                    },
                    {
                        'Sid': 'NeverAdministerStackSetsOrStackProtections',
                        'Effect': 'Deny',
                        'Action': ['cloudformation:DeleteStackSet',
                                   'cloudformation:UpdateTerminationProtection',
                                   'cloudformation:SetStackPolicy'],
                        'Resource': '*',
                    },
                    {
                        # Ordinary deployment must not rewrite secret payloads. CloudFormation
                        # rewrites a Secret's whole SecretString on update, wiping values filled
                        # in after bootstrap; such a change set fails and rolls back instead.
                        # Only the RDS secret's endpoint attachment may write a value.
                        'Sid': 'NeverWriteSecretValuesExceptTheDatabaseEndpoint',
                        'Effect': 'Deny',
                        'Action': ['secretsmanager:PutSecretValue'],
                        'NotResource': cls._service_arn(
                            'secretsmanager', f'secret:{cls.DEPLOY_RDS_SECRET_PATTERN}'),
                    },
                    {
                        'Sid': 'NeverRewriteSecretPayloadsOrPolicies',
                        'Effect': 'Deny',
                        'Action': ['secretsmanager:UpdateSecret', 'secretsmanager:RotateSecret',
                                   'secretsmanager:PutResourcePolicy',
                                   'secretsmanager:DeleteResourcePolicy'],
                        'Resource': '*',
                    },
                    cls.human_access_region_deny_statement(),
                ],
            },
        )

    def human_deploy_managed_policies(self) -> list:
        """ The allow documents exceed a role's 10240-character inline budget, so they are three
            customer managed policies (6144 each) created in this stack and attached to the role.
            Their CloudFormation-generated names contain 'InfraDeploy', which the guardrail
            protects.
        """
        documents = (
            ('InfraDeployStackPolicy', self.human_deploy_stack_policy(),
             'Deployment role: CloudFormation change sets and generated runtime identities.'),
            ('InfraDeployComputePolicy', self.human_deploy_compute_policy(),
             'Deployment role: network, instances, load balancing, ECS, Foursight serverless.'),
            ('InfraDeployDataPolicy', self.human_deploy_data_policy(),
             'Deployment role: datastores, keys, secrets, buckets, artifacts, registries, builds.'),
        )
        return [ManagedPolicy(self.name.logical_id(title), Description=description,
                              PolicyDocument=document)
                for title, document, description in documents]

    def human_deploy_role(self, principal_arns: list, policies: list) -> Role:
        """ Change-set deployment role. Trust is the same enumerated, source-identity-labelled,
            MFA-at-assumption trust as the other human roles; no account-root fallback.
        """
        return Role(
            self.DEPLOY_ROLE,
            Description='Change-set deployment of the c4-* CloudFormation stacks. Opt-in; see'
                        ' human_access.deploy.* in custom/config.json.',
            AssumeRolePolicyDocument=self.human_access_trust_policy(principal_arns),
            MaxSessionDuration=self.HUMAN_ACCESS_DEPLOY_SESSION_DURATION,
            ManagedPolicyArns=[Ref(policy) for policy in policies],
            Policies=[self.human_deploy_guardrail_policy()],
        )

    def build_human_deploy_role(self, template: Template) -> Template:
        """ Adds the deployment role and its policies if, and only if, human_access.deploy.enabled
            is on and human_access.deploy.trusted_principals is non-empty. Independent of the
            diagnose/remediate switches and principal lists.
        """
        if not self.human_deploy_role_requested():
            if self._human_access_flag(Settings.HUMAN_ACCESS_DEPLOY_ENABLED):
                logger.warning(f'{Settings.HUMAN_ACCESS_DEPLOY_ENABLED} is on but'
                               f' {Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS} is empty;'
                               f' not creating {self.DEPLOY_ROLE}.')
            return template
        principals = self._human_access_list(Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS)
        self.check_protected_names_fit(self.name.stack_name)
        policies = self.human_deploy_managed_policies()
        for policy in policies:
            template.add_resource(policy)
        role = self.human_deploy_role(principals, policies)
        template.add_resource(role)
        template.add_output(self.output_human_access_role(role))
        # Exported (unlike the other human-access outputs) because the datastore stack's KMS key
        # policy must name this role; see human_deploy_key_policy_statements.
        template.add_output(Output(
            self.name.logical_id(C4IAMExports.HUMAN_DEPLOY_ROLE_ARN),
            Description=f'ARN of the {role.title} deployment role, for the datastore key policy',
            Value=GetAtt(role, 'Arn'),
            Export=self.EXPORTS.export(C4IAMExports.HUMAN_DEPLOY_ROLE_ARN),
        ))
        return template

    @classmethod
    def human_deploy_role_requested(cls) -> bool:
        """ True when config builds the deployment role: its flag is on and its own principal
            list is non-empty. Other stacks (the datastore key policy) use the same predicate.
        """
        return (cls._human_access_flag(Settings.HUMAN_ACCESS_DEPLOY_ENABLED)
                and bool(cls._human_access_list(Settings.HUMAN_ACCESS_DEPLOY_PRINCIPALS)))

    # KMS key-policy grants for the deployment role on the datastore key. Deliberately not kms:*:
    # what CloudFormation's AWS::KMS::Key handlers call to create and update the key - PutKeyPolicy
    # is what KMS's lockout safety check requires of the caller of CreateKey - plus envelope
    # encryption through S3 for SSE-KMS buckets and packaged artifacts. Deletion, disabling, grants
    # and direct encrypt/re-encrypt are absent (and deletion/disabling are denied in IAM too).
    DEPLOY_KEY_MAINTENANCE_ACTIONS = (
        'kms:DescribeKey', 'kms:GetKeyPolicy', 'kms:PutKeyPolicy', 'kms:GetKeyRotationStatus',
        'kms:ListResourceTags', 'kms:TagResource', 'kms:UntagResource', 'kms:UpdateKeyDescription',
    )
    DEPLOY_KEY_USE_ACTIONS = ('kms:GenerateDataKey', 'kms:Decrypt')

    @classmethod
    def human_deploy_key_policy_statements(cls, deploy_role_arn) -> list:
        """ Statements added to a datastore key policy when the deployment role is configured.
            The key policy has no account-root statement, so the role needs these in addition to
            its IAM permissions (KMS dual authorization).
        """
        return [
            {
                'Sid': 'Allow the deployment role to create and maintain the key',
                'Effect': 'Allow',
                'Principal': {'AWS': [deploy_role_arn]},
                'Action': list(cls.DEPLOY_KEY_MAINTENANCE_ACTIONS),
                'Resource': '*',
            },
            {
                'Sid': 'Allow the deployment role to use the key through S3',
                'Effect': 'Allow',
                'Principal': {'AWS': [deploy_role_arn]},
                'Action': list(cls.DEPLOY_KEY_USE_ACTIONS),
                'Resource': '*',
                'Condition': {'StringEquals': {
                    'kms:ViaService': Join('.', ['s3', Region, 'amazonaws.com'])}},
            },
        ]

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
