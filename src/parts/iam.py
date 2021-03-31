from troposphere import AWS_REGION, AWS_ACCOUNT_ID, Template, Ref, Output
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
    EXPORTS = C4IAMExports()

    def build_template(self, template: Template) -> Template:
        """ Builds current IAM template, currently just the ECS assumed IAM role
            and instance profile.
        """
        iam_role = self.ecs_assumed_iam_role()
        template.add_resource(iam_role)
        instance_profile = self.ecs_instance_profile()
        template.add_resource(instance_profile)

        # add outputs
        template.add_output(self.output_assumed_iam_role(iam_role))
        template.add_output(self.output_instance_profile(instance_profile))
        return template

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

    @staticmethod
    def ecs_log_policy():
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

    def ecs_assumed_iam_role(self):
        """ Builds an IAM role for assumption by ECS containers. """
        policies = [
            self.ecs_secret_manager_policy(),  # to get env configuration
            self.ecs_access_policy(),  # to manage ECS
            self.ecs_es_policy(),  # to access ES
            self.ecs_sqs_policy(),  # to access SQS
            self.ecs_log_policy(),  # to log things
            self.ecs_ecr_policy(),  # to pull down container images
            self.ecs_web_service_policy()  # permissions for service
        ]
        return Role(
            self.ROLE_NAME,
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

    def ecs_instance_profile(self):
        """ Builds an instance profile for the above ECS Role. """
        return InstanceProfile(
            self.INSTANCE_PROFILE_NAME,
            Roles=[self.ecs_assumed_iam_role()]
        )

    def output_assumed_iam_role(self, resource: Role) -> Output:
        """ Creates output for ECS assumed IAM role """
        export_name = C4IAMExports.ECS_ASSUMED_IAM_ROLE
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