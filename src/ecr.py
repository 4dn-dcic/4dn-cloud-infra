from troposphere import (
    AWS_ACCOUNT_ID,
    AWS_REGION,
    Join,
    Ref,
    Output,
)
from troposphere.ecr import Repository
from awacs.aws import (
    Allow,
    Policy,
    AWSPrincipal,
    Statement,
)
import awacs.ecr as ecr


class C4ContainerRegistry:
    """ Contains a classmethod that builds an ECR template for this stack.
        TODO: Test, add to template.
    """

    @classmethod
    def ecr_push_statement(cls, principle='root'):
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

    @classmethod
    def ecr_pull_statement(cls, principle='root'):
        """ This statement gives the given principle pull access to ECR.
            This perm should be attached to the assumed IAM role of ECS.
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
                          cls.ecr_push_statement(), cls.ecr_pull_statement()
                      ]
                )

    @classmethod
    def repository(cls):
        """ Builds the ECR Repository. """
        return Repository(
            'CGAP-Docker',
            RepositoryName='WSGI',  # might be we need many of these?
            RepositoryPolicyText=cls.ecr_access_policy()
        )
