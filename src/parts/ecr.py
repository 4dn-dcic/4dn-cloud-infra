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
from dcicutils.cloudformation_utils import dehyphenate
from dcicutils.env_utils import is_fourfront_env
from troposphere.ecr import Repository
from ..base import ECOSYSTEM, ConfigManager, Settings
from ..parts.iam import C4IAMExports
from ..part import C4Part
from ..exports import C4Exports


class C4ECRExports(C4Exports):
    """ Holds exports for ECR. """
    PORTAL_REPO_URL = 'RepoURL'
    TIBANNA_REPO_URL = 'TibannaRepositoryURL'
    CNV_REPO_URL = 'CNVRepositoryURL'
    FASTQC_REPO_URL = 'FastqcRepositoryURL'
    MANTA_REPO_URL = 'MantaRepositoryURL'
    MD5_REPO_URL = 'MD5RepositoryURL'
    SNV_REPO_URL = 'SNVRepositoryURL'

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

        # NOTE: Behavior here assumes is_fourfront_env will return true
        # for this if we are building a fourfront environment. As such
        # when building a fourfront env, like with cgap we always use the
        # "fourfront-" prefix.
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)

        # build repos
        for rname, export in [
            (ECOSYSTEM, self.EXPORTS.PORTAL_REPO_URL),
            ('tibanna-awsf', self.EXPORTS.TIBANNA_REPO_URL),
            ('cnv', self.EXPORTS.CNV_REPO_URL),
            ('snv', self.EXPORTS.SNV_REPO_URL),
            ('manta', self.EXPORTS.MANTA_REPO_URL),
            ('md5', self.EXPORTS.MD5_REPO_URL),
            ('fastqc', self.EXPORTS.FASTQC_REPO_URL)
        ]:
            if is_fourfront_env(env_name) and rname != ECOSYSTEM:
                break  # do not add tibanna repos if building a fourfront env
            repo = self.repository(repo_name=rname)
            template.add_resource(repo)
            template.add_output(self.output_repo_url(repo, export))
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
        """ Builds an ECR Repository. """
        # We used to do this by environment, but now we make it per ecosystem.
        # repo_name = repo_name or ConfigManager.get_config_setting(Settings.ENV_NAME)
        repo_name = repo_name or ECOSYSTEM
        return Repository(
            dehyphenate(repo_name),  # must be lowercase, appears unused?
            RepositoryName=repo_name,  # might be we need many of these?
            RepositoryPolicyText=self.ecr_access_policy(),
            ImageScanningConfiguration={"ScanOnPush": True},
            Tags=self.tags.cost_tag_obj(),
        )

    def output_repo_url(self, resource: Repository, export_name) -> Output:
        """ Generates repo URL output """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Description=f'{logical_id} Image Repository URL',
            Value=Join('', [
                AccountId,
                '.dkr.ecr.',
                Region,
                '.amazonaws.com/',
                Ref(resource),
            ]),
            Export=self.EXPORTS.export(export_name)
        )
