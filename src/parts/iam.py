from awacs.aws import PolicyDocument, Statement, Action, Principal
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from troposphere import Region, AccountId, Template, Ref, Output, Join
from troposphere.iam import Role, InstanceProfile, Policy, User, AccessKey
from ..base import exportify
from ..part import C4Part
from ..exports import C4Exports


class C4IAMExports(C4Exports):
    """ Defines exports for IAM, consisting of:
            * assumed IAM role for ECS container
            * corresponding instance profile
    """
    ECS_ASSUMED_IAM_ROLE = exportify('ECSAssumedIAMRole')  # was 'ExportECSAssumedIAMRole'
    ECS_INSTANCE_PROFILE = exportify('ECSInstanceProfile')  # was 'ExportECSInstanceProfile'
    AUTOSCALING_IAM_ROLE = exportify('ECSAutoscalingIAMRole')  # was 'ExportECSAutoscalingIAMRole'
    S3_IAM_USER = exportify('ECSS3IAMUser')  # was 'ExportECSS3IAMUser'

    def __init__(self):
        parameter = 'IAMStackNameParameter'
        super().__init__(parameter)


class C4IAM(C4Part):
    """ Contains IAM Role configuration for CGAP.
        Right now, there is only one important IAM Role to configure.
        That is the assumed IAM role assigned to ECS.
    """
    ROLE_NAME = 'CGAPECSRole'
    INSTANCE_PROFILE_NAME = 'CGAPECSInstanceProfile'
    AUTOSCALING_ROLE_NAME = 'CGAPECSAutoscalingRole'
    EXPORTS = C4IAMExports()
    STACK_NAME_TOKEN = "iam"
    STACK_TITLE_TOKEN = "IAM"
    SHARING = 'ecosystem'

    def build_template(self, template: Template) -> Template:
        """ Builds current IAM template, currently just the ECS assumed IAM role
            and instance profile.
        """
        iam_role = self.ecs_assumed_iam_role()
        template.add_resource(iam_role)
        instance_profile = self.ecs_instance_profile()
        template.add_resource(instance_profile)
        autoscaling_iam_role = self.ecs_autoscaling_role()
        template.add_resource(autoscaling_iam_role)
        s3_iam_user = self.ecs_s3_iam_user()
        template.add_resource(s3_iam_user)
        s3_iam_user_access_key = self.ecs_s3_iam_user_access_key(s3_iam_user)
        template.add_resource(s3_iam_user_access_key)  # TODO: properly extract and pass this key

        # add outputs
        template.add_output(self.output_assumed_iam_role_or_user(iam_role,
                                                                 export_name=C4IAMExports.ECS_ASSUMED_IAM_ROLE))
        template.add_output(self.output_assumed_iam_role_or_user(autoscaling_iam_role,
                                                                 export_name=C4IAMExports.AUTOSCALING_IAM_ROLE))
        template.add_output(self.output_assumed_iam_role_or_user(s3_iam_user,
                                                                 export_name=C4IAMExports.S3_IAM_USER))
        template.add_output(self.output_instance_profile(instance_profile))
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
                    Resource='*',
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
                    Resource='*'  # XXX: Constrain further? Must match WRT log group and AWS logs
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
                    Resource='*',  # XXX: constrain further?
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
                    Resource='*',  # XXX: constrain further?
                )],
            ),
        )

    @staticmethod
    def ecs_cfn_policy() -> Policy:
        """ Gives access to the DescribeStacks API of cloudformation so that Application services can
            read outputs from stacks.

            Associated API: get_ecs_real_url
        """
        return Policy(
            PolicyName='ECSCfnPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'cloudformation:DescribeStacks',
                    ],
                    Resource='*',  # XXX: constrain further?
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
                    Resource='*',  # XXX: constrain further?
                )],
            ),
        )

    @staticmethod
    def ecs_autoscaling_access_policy() -> Policy:
        """ Contains policies needed for the IAM role assumed by the autoscaling service. """
        return Policy(
            PolicyName='CGAPAutoscalingPolicy',
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
            PolicyName='CGAPSTSPolicyforS3Access',
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
            self.ecs_web_service_policy(),  # permissions for service
        ]
        return Role(
            self.ROLE_NAME,
            # IMPORTANT: Required for EC2s to associate with ECS
            # XXX: AWSServiceRoleForECS needed for running ECS (?)
            ManagedPolicyArns=[
                "arn:aws:iam::aws:policy/service-role/AmazonEC2ContainerServiceforEC2Role",
                # NOTE: Will thinks that THIS is what we need, not the above:
                #
                # "arn:aws:iam::aws:policy/aws-service-role/AmazonECSServiceRolePolicy"
                #
                #   but using that URL gets me:
                #
                #   Cannot attach a Service Role Policy to a Customer Role.
                #   (Service: AmazonIdentityManagement;
                #    Status Code: 400;
                #    Error Code: PolicyNotAttachable;
                #    Request ID: 14573591-6e7c-4fd3-8d74-47edc41df495;
                #    Proxy: null)
            ],
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

    def ecs_instance_profile(self) -> InstanceProfile:
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            self.INSTANCE_PROFILE_NAME,
            Roles=[Ref(self.ecs_assumed_iam_role())]
        )

    def ecs_s3_iam_user(self) -> User:
        """ Builds an IAM user for federating access to S3 files. """
        logical_id = self.name.logical_id('ApplicationS3Federator')
        return User(
            logical_id,
            Policies=[
                self.ecs_s3_policy(),
                self.ecs_s3_user_sts_policy(),
            ],
            # Tags=self.tags.cost_tag_array(logical_id) does not accept tags - Will June 30th, 2021
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
