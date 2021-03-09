from troposphere import AWS_REGION, AWS_ACCOUNT_ID
from troposphere.iam import Role, InstanceProfile, Policy
from awacs.ecr import (
    GetAuthorizationToken,
    GetDownloadUrlForLayer,
    BatchGetImage,
    BatchCheckLayerAvailability,
)
from awacs.aws import PolicyDocument, Statement, Action, Principal


class C4IAM:
    """ Contains IAM Role configuration for CGAP.
        Right now, there is only one important IAM Role to configure.
        That is the assumed IAM role assigned to ECS.
    """
    ROLE_NAME = 'CGAPECSRole'
    INSTANCE_PROFILE_NAME = 'CGAPECSInstanceProfile'

    @staticmethod
    def ecs_sqs_policy(prefix='cgap-dev'):
        """ Grants ECS access to ElasticSearch.
            TODO: ensure cgaptriales is correct.
        """
        return Policy(
            PolicyName='ECSSQSAccessPolicy',
            PolicyDocument=dict(
                Statement=dict(
                    Effect='Allow',
                    Action=['sqs:*'],  # TODO: prune this slightly?
                    Resource=['arn:aws:sqs:%s:%s:%s*' %
                              (AWS_REGION, AWS_ACCOUNT_ID, prefix)]
                    )
            )
        )

    @staticmethod
    def ecs_es_policy(es_id='cgaptriales'):
        """ Grants ECS access to ElasticSearch.
            TODO: ensure cgaptriales is correct.
        """
        return Policy(
            PolicyName='ECSESAccessPolicy',
            PolicyDocument=dict(
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'es:*',
                    ],
                    Resource=['arn:aws:es:%s:%s:domain/%s' %
                              (AWS_REGION, AWS_ACCOUNT_ID, es_id)]
                )],
            )
        )

    @staticmethod
    def ecs_secret_manager_policy(secret_name='dev/beanstalk/cgap-dev'):
        """ Provides ECS access to the specified secret.
            The secret ID determines the environment name we are creating.
            TODO: Should this also be created here? Or manually uploaded?
        """
        return Policy(
            PolicyName='ECSSecretManagerPolicy',
            PolicyDocument=dict(
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'secretsmanager:GetSecretValue',
                    ],
                    Resource=['arn:aws:secretsmanager:%s:%s:secret:%s*' %
                              (AWS_REGION, AWS_ACCOUNT_ID, secret_name)]
                )],
            )
        )

    @staticmethod
    def ecs_assume_role_policy():
        """ Allow ECS to assume this role. """
        return Policy(
            PolicyName='ECSAssumeIAMRolePolicy',
            PolicyDocument=dict(
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
        return Policy(
            PolicyName='ECSManagementPolicy',
            PolicyDocument=dict(
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

    @classmethod
    def ecs_log_policy(cls):
        """ Grants ECS container the ability to log things. """
        return Policy(
            PolicyName='ECSLoggingPolicy',
            PolicyDocument=dict(
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'logs:Create*',
                        'logs.PutLogEvents',
                    ],
                    Resource='arn:aws:logs:*:*:*'  # XXX: Constrain further?
                )]
            )
        )

    @staticmethod
    def ecs_ecr_policy():
        return Policy(
            PolicyName='ECSECRPolicy',
            PolicyDocument=dict(
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
        return Policy(
            PolicyName='ECSWebServicePolicy',
            PolicyDocument=dict(
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

    @classmethod
    def ecs_assumed_iam_role(cls):
        """ Builds an IAM role for assumption by ECS containers. """
        policies = [
            cls.ecs_secret_manager_policy(),  # to get env configuration
            cls.ecs_access_policy(),  # to manage ECS
            cls.ecs_es_policy(),  # to access ES
            cls.ecs_sqs_policy(),  # to access SQS
            cls.ecs_log_policy(),  # to log things
            cls.ecs_ecr_policy(),  # to pull down container images
            cls.ecs_web_service_policy()  # permissions for service
        ]
        return Role(
            cls.ROLE_NAME,
            # Only allow ECS to assume this role
            AssumeRolePolicyDocument=PolicyDocument(Statement=[Statement(
                Effect='Allow',
                Action=[
                    Action('sts', 'AssumeRole')
                ],
                Principal=Principal('Service', 'ecs.amazonaws.com')
            )]),
            Policies=policies
        )

    @classmethod
    def ecs_instance_profile(cls):
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            cls.INSTANCE_PROFILE_NAME,
            Roles=[cls.ecs_assumed_iam_role()]
        )
