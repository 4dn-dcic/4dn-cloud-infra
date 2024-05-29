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
from dcicutils.misc_utils import snake_case_to_camel_case
from troposphere.ecr import Repository, ImageScanningConfiguration
from ..base import ECOSYSTEM, ConfigManager, Settings
from ..parts.iam import C4IAMExports
from ..part import C4Part
from ..exports import C4Exports


class C4ECRExports(C4Exports):
    """ Holds exports for ECR.
        For pipeline repository structure, see cgap-pipeline documentation.
    """
    PORTAL_REPO_URL = 'RepoURL'
    TIBANNA_REPO_URL = 'TibannaRepositoryURL'
    BASE_REPO_URL = 'BaseRepositoryURL'
    FASTQC_REPO_URL = 'FastqcRepositoryURL'
    MD5_REPO_URL = 'MD5RepositoryURL'
    UPSTREAM_SENTIEON_URL = 'UpstreamSentieonRepositoryURL'
    UPSTREAM_GATK_URL = 'UpstreamGATKRepositoryURL'
    SNV_GERMLINE_GATK_URL = 'SNVGermlineGATKURL'
    SNV_GERMLINE_GRANITE_URL = 'SNVGermlineGraniteURL'
    SNV_GERMLINE_MISC_URL = 'SNVGermlineMiscURL'
    SNV_GERMLINE_TOOLS_URL = 'SNVGermlineToolsURL'
    SNV_GERMLINE_VEP_URL = 'SNVGermlineVEPURL'
    SNV_SOMATIC_URL = 'SNVSomaticURL'
    CNV_GERMLINE_URL = 'CNVGermlineURL'
    MANTA_REPO_URL = 'MantaRepositoryURL'
    SV_GERMLINE_GRANITE_URL = 'SVGermlineGraniteURL'
    SV_GERMLINE_TOOLS_URL = 'SVGermlineToolsURL'
    SV_GERMLINE_VEP_URL = 'SVGermlineVEPURL'
    ASCAT_URL = 'AscatURL'
    SOMATIC_SENTION_URL = 'SomaticSentieonURL'

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
    SHARING = 'env'  # TODO: should be overridden if we are building a blue/green

    def build_template(self, template: Template) -> Template:
        # Adds IAM Stack Parameter
        template.add_parameter(Parameter(
            self.IAM_EXPORTS.reference_param_key,
            Description='Name of IAM stack for IAM role/instance profile references',
            Type='String',
        ))

        # NOTE: Nowadays we no longer use "main" as the repo name and always use the env name, in case
        # we want to bring up new envs in the same account - Will Oct 27 2023
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)

        # build repos
        # note that these are defined by the structure in cgap-pipeline-master - Will Dec 6 2021
        repo_export_pairs = [
            # Main application portal image
            (env_name or ECOSYSTEM, self.EXPORTS.PORTAL_REPO_URL),

            # Tibanna executor image
            ('tibanna-awsf', self.EXPORTS.TIBANNA_REPO_URL),

            # Misc
            ('base', self.EXPORTS.BASE_REPO_URL),
            ('fastqc', self.EXPORTS.FASTQC_REPO_URL),
            ('md5', self.EXPORTS.MD5_REPO_URL),

            # Alignment algorithms
            ('upstream_gatk', self.EXPORTS.UPSTREAM_GATK_URL),
            ('upstream_sentieon', self.EXPORTS.UPSTREAM_SENTIEON_URL),

            # SNV callers
            ('snv_germline_gatk', self.EXPORTS.SNV_GERMLINE_GATK_URL),
            ('snv_germline_granite', self.EXPORTS.SNV_GERMLINE_GRANITE_URL),
            ('snv_germline_misc', self.EXPORTS.SNV_GERMLINE_MISC_URL),
            ('snv_germline_tools', self.EXPORTS.SNV_GERMLINE_TOOLS_URL),
            ('snv_germline_vep', self.EXPORTS.SNV_GERMLINE_VEP_URL),
            ('snv_somatic', self.EXPORTS.SNV_SOMATIC_URL),

            # CNV/SV callers
            ('cnv_germline', self.EXPORTS.CNV_GERMLINE_URL),
            ('manta', self.EXPORTS.MANTA_REPO_URL),
            ('sv_germline_granite', self.EXPORTS.SV_GERMLINE_GRANITE_URL),
            ('sv_germline_tools', self.EXPORTS.SV_GERMLINE_TOOLS_URL),
            ('sv_germline_vep', self.EXPORTS.SV_GERMLINE_VEP_URL),
            ('ascat', self.EXPORTS.ASCAT_URL),

            # Sentieon callers
            ('somatic_sentieon', self.EXPORTS.SOMATIC_SENTION_URL),

        ]
        for rname, export in repo_export_pairs:
            if (ConfigManager.get_config_setting(Settings.APP_KIND) in ['ff', 'smaht'] and
                    rname not in [env_name, 'tibanna-awsf']):
                break  # do not add tibanna repos if building a fourfront/smaht env
            if self.SHARING == 'env' and rname == 'tibanna-awsf':
                break  # also exit if we are in a multi env setup (we do not build tibanna-awsf twice)
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
            dehyphenate(snake_case_to_camel_case(repo_name)),  # must be lowercase, no hyphens or underscores
            RepositoryName=repo_name,  # might be we need many of these?
            RepositoryPolicyText=self.ecr_access_policy(),
            ImageScanningConfiguration=ImageScanningConfiguration(ScanOnPush=True),
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
