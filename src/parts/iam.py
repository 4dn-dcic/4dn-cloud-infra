from troposphere import Region, AccountId, Template, Ref, Output, Join
from troposphere.iam import Role, InstanceProfile, Policy
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from awacs.aws import PolicyDocument, Statement, Action, Principal

from src.part import C4Part
from src.exports import C4Exports


class C4IAMExports(C4Exports):
    """ Defines exports for IAM, consisting of:
            * assumed IAM role for ECS container
            * corresponding instance profile
    """
    ECS_ASSUMED_IAM_ROLE = 'ExportECSAssumedIAMRole'
    ECS_INSTANCE_PROFILE = 'ExportECSInstanceProfile'
    AUTOSCALING_IAM_ROLE = 'ExportECSAutoscalingIAMRole'

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

        # add outputs
        template.add_output(self.output_assumed_iam_role(iam_role))
        template.add_output(self.output_assumed_iam_role(autoscaling_iam_role,
                                                         export_name=C4IAMExports.AUTOSCALING_IAM_ROLE))
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

    def ecs_sqs_policy(self, prefix='cgap-mastertest*'):
        """ Grants ECS access to ElasticSearch.
        """
        return Policy(
            PolicyName='ECSSQSAccessPolicy',
            PolicyDocument=dict(
                Version='2012-10-17',
                Statement=dict(
                    Effect='Allow',
                    Action=['sqs:*'],  # TODO: prune this slightly?
                    Resource=[self.build_sqs_arn(prefix)]
                )
            )
        )

    def ecs_es_policy(self, domain_name='c4datastore*'):
        """ Grants ECS access to ElasticSearch.
        """
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

    def ecs_secret_manager_policy(self, secret_name='dev/beanstalk/cgap-dev'):
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
    def ecs_assume_role_policy():
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
    def ecs_access_policy():
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
    def ecs_log_policy():
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
    def ecs_ecr_policy():
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
    def ecs_web_service_policy():
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
    def ecs_cfn_policy():
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
    def ecs_s3_policy():
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
    def ecs_autoscaling_access_policy():
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

    def ecs_assumed_iam_role(self):
        """ Builds a general purpose IAM role for use with ECS.
            TODO: split into several roles?
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
# Maybe?
#                "arn:aws:iam::aws:policy/aws-service-role/AmazonECSServiceRolePolicy"
            ],
            # IMPORTANT: BOTH ECS and EC2 need AssumeRole
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'ecs.amazonaws.com')
            ), Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'ec2.amazonaws.com')
            ), Statement(
                    Effect='Allow',
                    Action=[
                        Action('sts', 'AssumeRole')
                    ],
                    Principal=Principal('Service', 'ecs-tasks.amazonaws.com')
            )]),
            Policies=policies
        )

    def ecs_autoscaling_role(self):
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

    def ecs_instance_profile(self):
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            self.INSTANCE_PROFILE_NAME,
            Roles=[Ref(self.ecs_assumed_iam_role())]
        )

    def output_assumed_iam_role(self, resource: Role, export_name=C4IAMExports.ECS_ASSUMED_IAM_ROLE) -> Output:
        """ Creates output for ECS assumed IAM role """
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