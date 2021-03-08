from troposphere import AWS_REGION, AWS_ACCOUNT_ID
from troposphere.iam import Role, InstanceProfile, Policy
from awacs.aws import PolicyDocument


class C4IAM:
    """ Contains IAM Role configuration for CGAP.
        Right now, there is only one important IAM Role to configure.
        That is the assumed IAM role assigned to ECS.
    """
    ROLE_NAME = 'CGAPECSRole'
    INSTANCE_PROFILE_NAME = 'CGAPECSInstanceProfile'

    @classmethod
    def ecs_sqs_acl(cls, prefix='cgap-dev'):
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

    @classmethod
    def ecs_es_acl(cls, es_id='cgaptriales'):
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
                    Resource=['arn:aws:secretsmanager:%s:%s:secret:%s*' %
                              (AWS_REGION, AWS_ACCOUNT_ID, es_id)]
                )],
            )
        )

    @classmethod
    def ecs_secret_manager_acl(cls, secret_name='dev/beanstalk/cgap-dev'):
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

    @classmethod
    def ecs_assume_role_acl(cls):
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

    @classmethod
    def ecs_access_policy(cls):
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
    def ecs_assumed_iam_role(cls):
        """ Builds an IAM role for assumption by ECS containers.
            Give access to:
                * SecretManager, to retrieve environment configuration
                * ES (back-end)
                * SQS (back-end)
                * TODO? RDS (maybe can already connect?)
        """
        return Role(
            cls.ROLE_NAME,
            AssumeRolePolicyDocument=PolicyDocument(
                # Statement=[
                #     TODO fix me
                #     cls.ecs_assume_role_acl(),
                # ]
            ),
            Policies=[
                cls.ecs_secret_manager_acl(), cls.ecs_access_policy(),
                cls.ecs_es_acl(), cls.ecs_sqs_acl()
            ]
        )

    @classmethod
    def ecs_instance_profile(cls):
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            cls.INSTANCE_PROFILE_NAME,
            Roles=[cls.ecs_assumed_iam_role()]
        )
