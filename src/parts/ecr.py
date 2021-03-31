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
from src.part import C4Part
from src.exports import C4Exports


class C4ECRExports(C4Exports):
    """ Holds exports for ECR. """
    ECR_REPO_URL = 'ECRRepoURL'

    def __init__(self):
        parameter = 'ECRStackNameParameter'
        super().__init__(parameter)


class QCContainerRegistry(C4Part):
    """ Contains a classmethod that builds an ECR template for this stack.
        NOTE: IAM setup must be done before this.
    """
    EXPORTS = C4ECRExports()

    def build_template(self, template: Template) -> Template:
        repo = self.repository()
        template.add_resource(repo)
        template.add_output(self.output_repo_url(repo))
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

    def ecr_access_policy(self):
        """ Contains ECR access policy """
        return Policy(Version='2008-10-17',
                      Statement=[
                          # 2 statements - push/pull to whoever will be uploading the image
                          # and pull to the assumed IAM role
                          self.ecr_push_acl(), self.ecr_pull_acl()
                      ]
                )

    def repository(self):
        """ Builds the ECR Repository. """
        return Repository(
            'CGAPDocker',
            RepositoryName='WSGI',  # might be we need many of these?
            RepositoryPolicyText=self.ecr_access_policy()
        )

    @staticmethod
    def output_repo_url(resource: Repository):
        """ Generates repo URL output """
        return Output(
            C4ECRExports.ECR_REPO_URL,
            Description='CGAPDocker Image Repository URL',
            Value=Join('', [
                Ref(AWS_ACCOUNT_ID),
                '.dkr.ecr.',
                Ref(AWS_REGION),
                '.amazonaws.com/',
                Ref(resource),
            ]),
        )
