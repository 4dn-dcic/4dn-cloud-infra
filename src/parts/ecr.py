from troposphere import (
    AWS_ACCOUNT_ID,
    AWS_REGION,
    Join,
    Ref,
    Template,
    Output,
    Export,
    Sub,
    ImportValue
)
from troposphere.ecr import Repository
from awacs.aws import (
    Allow,
    Policy,
    AWSPrincipal,
    Statement,
)
import awacs.ecr as ecr
from .iam import C4IAM
from src.part import QCPart


class QCContainerRegistry(QCPart):
    """ Contains a classmethod that builds an ECR template for this stack.
        NOTE: IAM setup must be done before this.
    """

    def build_template(self, template: Template) -> Template:
        repo = self.repository()
        template.add_resource(repo)
        template.add_output(Output(
            'CGAPDockerRepoURL',
            Description="CGAPDocker Image Repository",
            Value=Join("", [
                Ref(AWS_ACCOUNT_ID),
                ".dkr.ecr.",
                Ref(AWS_REGION),
                ".amazonaws.com/",
                Ref(repo),
            ]),
        ))
        return template

    @staticmethod
    def ecr_push_acl(principle='root'):
        """ This statement gives the root user push/pull access to ECR.
            TODO: 'root' is likely not correct.
        """
        return Statement(
            Sid="AllowPushPull",  # allow push/pull
            Effect=Allow,
            Principal=AWSPrincipal([
                Join("", [
                    "arn:aws:iam::",
                    Ref(AWS_ACCOUNT_ID),
                    ":", principle
                ])
            ]),
            Action=[
                ecr.GetDownloadUrlForLayer,
                ecr.BatchGetImage,
                ecr.BatchCheckLayerAvailability,
                ecr.PutImage,
                ecr.InitiateLayerUpload,
                ecr.UploadLayerPart,
                ecr.CompleteLayerUpload,
            ])

    @staticmethod
    def ecr_pull_acl(principle=C4IAM.ROLE_NAME):
        """ This statement gives the given principle pull access to ECR.
            This perm should be attached to the assumed IAM role of ECS.

            ROLE_NAME corresponds to the assumed IAM role of ECS. See iam.py.
        """
        return Statement(
                Sid="AllowPull",  # allow pull only
                Effect=Allow,
                Principal=AWSPrincipal([
                    Join("", [
                        "arn:aws:iam::",
                        Ref(AWS_ACCOUNT_ID),
                        ":", principle
                    ])
                ]),
                Action=[
                    ecr.GetDownloadUrlForLayer,
                    ecr.BatchGetImage,
                    ecr.BatchCheckLayerAvailability,
                    ecr.InitiateLayerUpload,
                    ecr.UploadLayerPart,
                    ecr.CompleteLayerUpload,
                ])

    @classmethod
    def ecr_access_policy(cls):
        """ Contains ECR access policy """
        return Policy(Version='2008-10-17',
                      Statement=[
                          # 2 statements - push/pull to whoever will be uploading the image
                          # and pull to the assumed IAM role
                          cls.ecr_push_acl(), cls.ecr_pull_acl()
                      ]
                )

    @classmethod
    def repository(cls):
        """ Builds the ECR Repository. """
        return Repository(
            'CGAPDocker',
            RepositoryName='WSGI',  # might be we need many of these?
            RepositoryPolicyText=cls.ecr_access_policy()
        )
