import os
from troposphere import (
    AccountId,
    Region,
    Join,
    Ref,
    Template,
    Output,
    Parameter
)
from troposphere.ecr import Repository
from awacs.aws import (
    Allow,
    Policy,
    AWSPrincipal,
    Statement,
)
import awacs.ecr as ecr
from src.constants import ENV_NAME
from src.parts.iam import C4IAMExports
from src.part import C4Part
from src.exports import C4Exports


class C4ECRExports(C4Exports):
    """ Holds exports for ECR. """
    ECR_REPO_URL = 'ECRRepoURL'

    def __init__(self):
        parameter = 'ECRStackNameParameter'
        super().__init__(parameter)


class C4ContainerRegistry(C4Part):
    """ Contains a classmethod that builds an ECR template for this stack.
        NOTE: IAM setup must be done before this.
    """
    EXPORTS = C4ECRExports()
    IAM_EXPORTS = C4IAMExports()

    def build_template(self, template: Template) -> Template:
        # Adds IAM Stack Parameter
        template.add_parameter(Parameter(
            self.IAM_EXPORTS.reference_param_key,
            Description='Name of IAM stack for IAM role/instance profile references',
            Type='String',
        ))

        repo = self.repository()
        template.add_resource(repo)
        template.add_output(self.output_repo_url(repo))
        return template

    def build_assumed_role_arn(self):
        return Join('', ['arn:', 'aws:', 'iam::', AccountId, ':role/',
                         self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
                         ]
                    )

    def ecr_push_acl(self):
        """ This statement gives the root user push/pull access to ECR.
        """
        return Statement(
            Sid='AllowPushPull',  # allow push/pull
            Effect=Allow,
            Principal=AWSPrincipal([
                self.build_assumed_role_arn()
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

    def ecr_pull_acl(self):
        """ This statement gives the given principle pull access to ECR.
            This perm should be attached to the assumed IAM role of ECS.

            ROLE_NAME corresponds to the assumed IAM role of ECS. See iam.py.
        """
        return Statement(
                Sid='AllowPull',  # allow pull only
                Effect=Allow,
                Principal=AWSPrincipal([
                    self.build_assumed_role_arn()
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
        return Policy(Statement=[
                          # 2 statements - push/pull to whoever will be uploading the image
                          # and pull to the assumed IAM role
                          self.ecr_push_acl(), self.ecr_pull_acl()
                      ], Version='2012-10-17',
        )

    def repository(self, name=None):
        """ Builds the ECR Repository. """
        name = name or os.environ.get(ENV_NAME) or 'cgap-mastertest'
        return Repository(
            'cgapdocker',  # must be lowercase, appears unused?
            RepositoryName=name,  # might be we need many of these?
            RepositoryPolicyText=self.ecr_access_policy(),
            # Tags=self.tags.cost_tag_array(), XXX: bug in troposphere - does not take tags array
        )

    def output_repo_url(self, resource: Repository):
        """ Generates repo URL output """
        export_name = C4ECRExports.ECR_REPO_URL
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description='CGAPDocker Image Repository URL',
            Value=Join('', [
                AccountId,
                '.dkr.ecr.',
                Region,
                '.amazonaws.com/',
                Ref(resource),
            ]),
            Export=self.EXPORTS.export(export_name)
        )
