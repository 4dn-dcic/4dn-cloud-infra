import awacs.ecr as ecr

from awacs.aws import (
    Allow,
    Policy,
    AWSPrincipal,
    Statement,
)
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
from ..base import ECOSYSTEM
from ..parts.iam import C4IAMExports
from ..part import C4Part
from ..exports import C4Exports


class C4ECRExports(C4Exports):
    """ Holds exports for ECR. """
    CGAP_REPO_URL = 'RepoURL'
    TIBANNA_REPO_URL = 'TibannaRepoURL'

    def __init__(self):
        parameter = 'ECRStackNameParameter'
        super().__init__(parameter)


class C4ContainerRegistry(C4Part):
    """ Contains a classmethod that builds an ECR template for this stack.
        NOTE: IAM setup must be done before this.
    """
    IAM_EXPORTS = C4IAMExports()
    EXPORTS = C4ECRExports()

    STACK_NAME_TOKEN = "ecr"
    STACK_TITLE_TOKEN = "ECR"
    SHARING = 'ecosystem'

    def build_template(self, template: Template) -> Template:
        # Adds IAM Stack Parameter
        template.add_parameter(Parameter(
            self.IAM_EXPORTS.reference_param_key,
            Description='Name of IAM stack for IAM role/instance profile references',
            Type='String',
        ))

        repo = self.repository()
        template.add_resource(repo)
        template.add_output(self.output_repo_url(repo, self.EXPORTS.CGAP_REPO_URL))
        tibanna_repo = self.tibanna_awsf_repository()
        template.add_resource(tibanna_repo)
        template.add_output(self.output_repo_url(tibanna_repo, self.EXPORTS.TIBANNA_REPO_URL))
        return template

    def build_assumed_role_arn(self):
        return Join('', ['arn:', 'aws:', 'iam::', AccountId, ':role/',
                         self.IAM_EXPORTS.import_value(C4IAMExports.ECS_ASSUMED_IAM_ROLE)
                         ]
                    )

    def ecr_push_acl(self) -> Statement:
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

    def ecr_pull_acl(self) -> Statement:
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

    def ecr_access_policy(self) -> Policy:
        """ Contains ECR access policy """
        return Policy(
            Statement=[
                # Two statements:
                # 1. push/pull to whoever will be uploading the image
                self.ecr_push_acl(),
                # 2. pull to the assumed IAM role
                self.ecr_pull_acl()
            ],
            Version='2012-10-17',
        )

    def repository(self, repo_name=None) -> Repository:
        """ Builds the ECR Repository for the portal. """
        # We used to do this by environment, but now we make it per ecosystem.
        # repo_name = repo_name or ConfigManager.get_config_setting(Settings.ENV_NAME)
        repo_name = repo_name or ECOSYSTEM
        return Repository(
            'cgapdocker',  # must be lowercase, appears unused?
            RepositoryName=repo_name,  # might be we need many of these?
            RepositoryPolicyText=self.ecr_access_policy(),
            ImageScanningConfiguration={"ScanOnPush": True},
            Tags=self.tags.cost_tag_obj(),
        )

    def tibanna_awsf_repository(self) -> Repository:
        """ Builds Tibanna-awsf ECR Repository """
        return Repository(
            'tibannaawsf',
            RepositoryName='tibanna-awsf',
            RepositoryPolicyText=self.ecr_access_policy(),
            Tags=self.tags.cost_tag_obj(),
        )

    def output_repo_url(self, resource: Repository, export_name) -> Output:
        """ Generates repo URL output """
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
