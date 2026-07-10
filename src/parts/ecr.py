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
    # Crowdstrike Falcon sensor sidecar image (built into ECR for ECS task sidecar use).
    FALCON_SENSOR_URL = 'FalconSensorURL'

    def __init__(self):
        parameter = 'ECRStackNameParameter'
        super().__init__(parameter)


# Single source of truth for the fixed (non-env) ECR repositories this stack creates, as
# (repo_name, C4ECRExports attribute name) pairs, in the order they are added to the template.
# src/parts/iam.py imports ECR_REPO_NAMES to scope ECS image-pull permissions to exactly these
# repositories (plus the env portal repo), so the IAM scope cannot drift out of sync with the
# repositories that actually exist (see SEC-1). Order matters: 'falcon-sensor' and 'tibanna-awsf'
# must stay first because build_template's ff/smaht short-circuit relies on it.
_ECR_FIXED_REPO_EXPORTS = [
    # Crowdstrike Falcon sensor sidecar image
    ('falcon-sensor', 'FALCON_SENSOR_URL'),
    # Tibanna executor image
    ('tibanna-awsf', 'TIBANNA_REPO_URL'),
    # Misc
    ('base', 'BASE_REPO_URL'),
    ('fastqc', 'FASTQC_REPO_URL'),
    ('md5', 'MD5_REPO_URL'),
    # Alignment algorithms
    ('upstream_gatk', 'UPSTREAM_GATK_URL'),
    ('upstream_sentieon', 'UPSTREAM_SENTIEON_URL'),
    # SNV callers
    ('snv_germline_gatk', 'SNV_GERMLINE_GATK_URL'),
    ('snv_germline_granite', 'SNV_GERMLINE_GRANITE_URL'),
    ('snv_germline_misc', 'SNV_GERMLINE_MISC_URL'),
    ('snv_germline_tools', 'SNV_GERMLINE_TOOLS_URL'),
    ('snv_germline_vep', 'SNV_GERMLINE_VEP_URL'),
    ('snv_somatic', 'SNV_SOMATIC_URL'),
    # CNV/SV callers
    ('cnv_germline', 'CNV_GERMLINE_URL'),
    ('manta', 'MANTA_REPO_URL'),
    ('sv_germline_granite', 'SV_GERMLINE_GRANITE_URL'),
    ('sv_germline_tools', 'SV_GERMLINE_TOOLS_URL'),
    ('sv_germline_vep', 'SV_GERMLINE_VEP_URL'),
    ('ascat', 'ASCAT_URL'),
    # Sentieon callers
    ('somatic_sentieon', 'SOMATIC_SENTION_URL'),
]

# Fixed repo names only (the env portal repo is named after ENV_NAME and handled separately).
ECR_REPO_NAMES = [name for name, _ in _ECR_FIXED_REPO_EXPORTS]


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

        # NOTE: Nowadays we no longer use "main" as the repo name and always use the env name, in case
        # we want to bring up new envs in the same account - Will Oct 27 2023
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)

        # build repos
        # note that these are defined by the structure in cgap-pipeline-master - Will Dec 6 2021
        # The fixed repo names live in _ECR_FIXED_REPO_EXPORTS (module-level) so IAM can import
        # ECR_REPO_NAMES and scope pulls to exactly these repos (see SEC-1).
        repo_export_pairs = [
            # Main application portal image
            (env_name or ECOSYSTEM, self.EXPORTS.PORTAL_REPO_URL),
        ] + [(name, getattr(self.EXPORTS, export_attr)) for name, export_attr in _ECR_FIXED_REPO_EXPORTS]
        for rname, export in repo_export_pairs:
            if (ConfigManager.get_config_setting(Settings.APP_KIND) in ['ff', 'smaht'] and
                    rname not in [env_name, 'tibanna-awsf', 'falcon-sensor']):
                # skip pipeline repos when building a fourfront/smaht env. Use `continue`, not
                # `break`, so it is not order-dependent on the allowlisted repos coming first (CLN-14).
                continue
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
