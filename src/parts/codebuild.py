from troposphere import Template, Parameter, AccountId, Join, Region, Ref, Output, GetAtt
from troposphere.codebuild import (
    Artifacts, Environment, Project, Source, SourceAuth, VpcConfig, SourceCredential, GitSubmodulesConfig,
    LogsConfig, CloudWatchLogs
)
from troposphere.iam import Role, Policy
from troposphere.logs import LogGroup
from tibanna._version import __version__ as tibanna_version
from dcicutils.cloudformation_utils import camelize
from dcicutils.common import REGION  # note to deploy outside us-east-1 you will need to change this
from .network import C4NetworkExports
from .srce_network import C4SRCENetworkExports
from .appconfig import C4AppConfigExports
from .shared_secrets import C4SharedSecretsExports
from ..part import C4Part
from ..exports import C4Exports, exportify
from ..base import ConfigManager, Settings, Secrets, APP_DEPLOYMENT, DeploymentParadigm, APP_KIND


class C4CodeBuildExports(C4Exports):
    """ Defines export metadata for codebuild """

    BLUE_CB_URL = exportify('BlueCodeBuildURL')
    GREEN_CB_URL = exportify('GreenCodeBuildURL')

    @classmethod
    def output_project_key(cls, project_name):
        """ Builds output key for the build project name """
        return f'CodeBuildFor{project_name}'

    @classmethod
    def output_project_iam_role(cls, project_name):
        """ Builds output key for the IAM role associated with this build project """
        return f'CodeBuildIAMRoleFor{project_name}'

    def __init__(self):
        parameter = 'CodeBuildStackNameParameter'
        super().__init__(parameter)


class C4CodeBuild(C4Part):
    DEFAULT_COMPUTE_TYPE = 'BUILD_GENERAL1_MEDIUM'  # will go slightly faster and needed for tibanna-awsf
    BUILD_TYPE = 'LINUX_CONTAINER'
    BUILD_IMAGE = 'aws/codebuild/standard:6.0'
    DEFAULT_ECOSYSTEM_NAME = 'main'
    DEFAULT_ECR_REPO_NAME = DEFAULT_ECOSYSTEM_NAME
    DEFAULT_GITHUB_REPOSITORY = 'https://github.com/dbmi-bgm/cgap-portal'
    DEFAULT_GITHUB_PIPELINE_REPOSITORY = 'https://github.com/dbmi-bgm/cgap-pipeline-main'
    SMAHT_GITHUB_REPOSITORY = 'https://github.com/smaht-dac/main-pipelines'
    DEFAULT_EXTERNAL_GITHUB_PIPELINE_REPOSITORY = 'https://github.com/dbmi-bgm/cgap-pipeline-contribution'
    DEFAULT_TIBANNA_REPOSITORY = 'https://github.com/4dn-dcic/tibanna'
    STACK_NAME_TOKEN = 'codebuild'
    STACK_TITLE_TOKEN = 'CodeBuild'
    DEFAULT_DEPLOY_BRANCH = 'master'
    DEFAULT_PIPELINE_DEPLOY_BRANCH = 'v1.0.0'  # version release tag for cgap-pipeline-main
    DEFAULT_EXTERNAL_GITHUB_PIPELINE_BRANCH = 'v1.0.0'  # TODO: this should be verified
    DEFAULT_LOG_RETENTION_DAYS = 30  # CloudWatch retention for CodeBuild logs (override via codebuild.log_retention_days)
    # DockerHub credentials (username + PAT) and Crowdstrike Falcon credentials now live in
    # the appconfig stack and are imported here via cross-stack ImportValue. Keys below
    # mirror the JSON shape of the appconfig-owned DockerHub secret.
    DOCKERHUB_SECRET_USERNAME_KEY = 'username'
    DOCKERHUB_SECRET_TOKEN_KEY = 'token'
    NETWORK_EXPORTS = C4NetworkExports()
    APPCONFIG_EXPORTS = C4AppConfigExports()
    SHARED_SECRETS_EXPORTS = C4SharedSecretsExports()
    EXPORTS = C4CodeBuildExports()

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))
        # AppConfig Stack Parameter — needed to ImportValue the Falcon secret ARNs.
        template.add_parameter(Parameter(
            self.APPCONFIG_EXPORTS.reference_param_key,
            Description='Name of appconfig stack for Falcon secret ARN ImportValue references',
            Type='String',
        ))
        # SharedSecrets Stack Parameter — ecosystem-scoped stack that owns DockerHub credentials.
        template.add_parameter(Parameter(
            self.SHARED_SECRETS_EXPORTS.reference_param_key,
            Description='Name of shared-secrets stack for DockerHub credentials ImportValue reference',
            Type='String',
        ))

        portal_env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        pipeline_project_name = portal_env_name + '-pipeline-builder'
        external_pipeline_project_name = portal_env_name + '-external-pipeline-builder'
        tibanna_project_name = portal_env_name + '-tibanna-awsf-builder'

        # IAM role for cb builds
        iam_role = self.cb_iam_role(project_name=portal_env_name)
        template.add_resource(iam_role)
        template.add_output(self.output_value(resource=iam_role,
                                              export_name=C4CodeBuildExports.output_project_iam_role(
                                                  project_name=portal_env_name
                                              )))
        tibanna_iam_role = self.cb_iam_role(project_name=tibanna_project_name)
        template.add_resource(tibanna_iam_role)
        template.add_output(self.output_value(resource=tibanna_iam_role,
                                              export_name=C4CodeBuildExports.output_project_iam_role(
                                                  project_name=tibanna_project_name
                                              )))

        # credentials for cb
        creds = self.cb_source_credential()
        template.add_resource(creds)

        # Build project for portal image in blue/green
        if APP_DEPLOYMENT == DeploymentParadigm.BLUE_GREEN:
            for env, export in {
                f'-{DeploymentParadigm.BLUE}': C4CodeBuildExports.BLUE_CB_URL,
                f'-{DeploymentParadigm.GREEN}': C4CodeBuildExports.GREEN_CB_URL
            }.items():
                env_name = ConfigManager.get_config_setting(Settings.ENV_NAME) + env
                template.add_resource(self.cb_log_group(project_name=env_name))
                build_project = self.cb_project(
                    project_name=env_name,
                    iam_role=iam_role,
                    github_repo_url=ConfigManager.get_config_setting(Settings.CODEBUILD_GITHUB_REPOSITORY_URL,
                                                                     default=self.DEFAULT_GITHUB_REPOSITORY),
                    branch=ConfigManager.get_config_setting(Settings.CODEBUILD_DEPLOY_BRANCH,
                                                            default=self.DEFAULT_DEPLOY_BRANCH),
                    environment=self.cb_portal_environment_vars(repo_name=ConfigManager.get_config_setting(
                        Settings.ENV_NAME), image_tag=env.lstrip('-'))
                )
                template.add_resource(build_project)
                template.add_output(self.output_value(resource=build_project,
                                                      export_name=C4CodeBuildExports.output_project_key(
                                                          project_name=env_name
                                                      )))
        else:  # standalone
            template.add_resource(self.cb_log_group(project_name=portal_env_name))
            build_project = self.cb_project(
                project_name=portal_env_name,
                iam_role=iam_role,
                github_repo_url=ConfigManager.get_config_setting(Settings.CODEBUILD_GITHUB_REPOSITORY_URL,
                                                                 default=self.DEFAULT_GITHUB_REPOSITORY),
                branch=ConfigManager.get_config_setting(Settings.CODEBUILD_DEPLOY_BRANCH,
                                                        default=self.DEFAULT_DEPLOY_BRANCH),
                environment=self.cb_portal_environment_vars(repo_name=ConfigManager.get_config_setting(
                        Settings.ENV_NAME))
            )
            template.add_resource(build_project)
            template.add_output(self.output_value(resource=build_project,
                                                  export_name=C4CodeBuildExports.output_project_key(
                                                      project_name=portal_env_name
                                                  )))
        if APP_KIND == 'cgap':
            pipeline_iam_role = self.cb_iam_role(project_name=pipeline_project_name, include_falcon=True)
            template.add_resource(pipeline_iam_role)
            external_pipeline_iam_role = self.cb_iam_role(project_name=external_pipeline_project_name)
            template.add_resource(external_pipeline_iam_role)
            template.add_output(self.output_value(resource=pipeline_iam_role,
                                                  export_name=C4CodeBuildExports.output_project_iam_role(
                                                      project_name=pipeline_project_name
                                                  )))
            template.add_output(self.output_value(resource=external_pipeline_iam_role,
                                                  export_name=C4CodeBuildExports.output_project_iam_role(
                                                      project_name=external_pipeline_project_name
                                                  )))
            # Build project for pipeline images
            template.add_resource(self.cb_log_group(project_name=pipeline_project_name))
            pipeline_build_project = self.cb_project(
                project_name=pipeline_project_name,
                iam_role=pipeline_iam_role,
                github_repo_url=self.DEFAULT_GITHUB_PIPELINE_REPOSITORY,
                branch=self.DEFAULT_PIPELINE_DEPLOY_BRANCH,
                environment=self.cb_pipeline_environment_vars()
            )
            template.add_resource(pipeline_build_project)
            template.add_output(self.output_value(resource=pipeline_build_project,
                                                  export_name=C4CodeBuildExports.output_project_key(
                                                      project_name=pipeline_project_name
                                                  )))

            # Build project for external pipeline images
            template.add_resource(self.cb_log_group(project_name=external_pipeline_project_name))
            external_pipeline_build_project = self.cb_project(
                project_name=external_pipeline_project_name,
                iam_role=external_pipeline_iam_role,
                github_repo_url=self.DEFAULT_EXTERNAL_GITHUB_PIPELINE_REPOSITORY,
                branch=self.DEFAULT_EXTERNAL_GITHUB_PIPELINE_BRANCH,
                environment=self.cb_external_pipeline_environment_vars()
            )
            template.add_resource(external_pipeline_build_project)
            template.add_output(self.output_value(resource=external_pipeline_build_project,
                                                  export_name=C4CodeBuildExports.output_project_key(
                                                      project_name=external_pipeline_project_name
                                                  )))

        elif APP_KIND == 'smaht':
            pipeline_iam_role = self.cb_iam_role(project_name=pipeline_project_name, include_falcon=True)
            template.add_resource(pipeline_iam_role)
            template.add_output(self.output_value(resource=pipeline_iam_role,
                                                  export_name=C4CodeBuildExports.output_project_iam_role(
                                                      project_name=pipeline_project_name
                                                  )))
            # Build project for pipeline images
            template.add_resource(self.cb_log_group(project_name=pipeline_project_name))
            pipeline_build_project = self.cb_project(
                project_name=pipeline_project_name,
                iam_role=pipeline_iam_role,
                github_repo_url=self.SMAHT_GITHUB_REPOSITORY,
                branch='main',
                environment=self.cb_pipeline_environment_vars()
            )
            template.add_resource(pipeline_build_project)
            template.add_output(self.output_value(resource=pipeline_build_project,
                                                  export_name=C4CodeBuildExports.output_project_key(
                                                      project_name=pipeline_project_name
                                                  )))

        # Build project for Tibanna AWSF
        template.add_resource(self.cb_log_group(project_name=tibanna_project_name))
        tibanna_build_project = self.cb_project(
            project_name=tibanna_project_name,
            iam_role=tibanna_iam_role,
            github_repo_url=self.DEFAULT_TIBANNA_REPOSITORY,
            branch=tibanna_version,  # default branch to version
            environment=self.cb_tibanna_environment_vars()
        )
        template.add_resource(tibanna_build_project)
        template.add_output(self.output_value(resource=tibanna_build_project,
                                              export_name=C4CodeBuildExports.output_project_key(
                                                  project_name=tibanna_project_name
                                              )))
        return template

    @staticmethod
    def cb_vpc_policy() -> Policy:
        return Policy(  # give CB access to network so can run in private VPC subnets
            PolicyName='CBNetworkPolicy',
            PolicyDocument={
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateNetworkInterface",
                            "ec2:DescribeDhcpOptions",
                            "ec2:DescribeNetworkInterfaces",
                            "ec2:DeleteNetworkInterface",
                            "ec2:DescribeSubnets",
                            "ec2:DescribeSecurityGroups",
                            "ec2:DescribeVpcs"
                        ],
                        "Resource": "*"
                    },
                    {
                        "Effect": "Allow",
                        "Action": [
                            "ec2:CreateNetworkInterfacePermission"
                        ],
                        "Resource": [Join(':', ["arn:aws:ec2", Region, AccountId, "network-interface/*"])],
                    }
                ]
            }
        )

    def cb_iam_role(self, *, project_name, include_dockerhub=True, include_falcon=False) -> Role:
        return Role(
            f'CodeBuildRoleFor{camelize(project_name)}',
            AssumeRolePolicyDocument=dict(
                Version='2012-10-17',
                Statement=[dict(
                    Effect='Allow',
                    Action=[
                        'sts:AssumeRole',
                    ],
                    Principal=dict(Service=['codebuild.amazonaws.com']),
                )],
            ),
            Policies=[
                self.cb_vpc_policy(),
            ] + ([self.cb_external_secrets_policy(include_dockerhub=include_dockerhub,
                                                  include_falcon=include_falcon)]
                 if include_dockerhub or include_falcon else []) + self.cb_least_privilege_policies(),
        )

    def cb_least_privilege_policies(self) -> list:
        """ Inline least-privilege policies replacing the four account-wide FullAccess/Admin
            managed policies (AmazonS3FullAccess, CloudWatchFullAccess, AWSCodeBuildAdminAccess,
            AmazonEC2ContainerRegistryPowerUser) previously attached to the CodeBuild role (SEC-8).
            Scoped to the resources a docker build/push in this ecosystem actually touches. """
        # Lazy import avoids any import-cycle risk with the ECR part.
        from .ecr import ECR_REPO_NAMES
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        repo_arns = [Join(':', ['arn', 'aws', 'ecr', Region, AccountId, f'repository/{name}'])
                     for name in [env_name] + ECR_REPO_NAMES]
        s3_bucket_arn = f'arn:aws:s3:::{env_name}-*'
        log_group_arn = Join(':', ['arn', 'aws', 'logs', Region, AccountId, 'log-group:/aws/codebuild/*'])
        log_stream_arn = Join(':', ['arn', 'aws', 'logs', Region, AccountId,
                                    'log-group:/aws/codebuild/*:log-stream:*'])
        report_group_arn = Join(':', ['arn', 'aws', 'codebuild', Region, AccountId, 'report-group/*'])
        return [
            Policy(  # S3: this env's buckets (e.g. the application-version bucket)
                PolicyName='CBS3Access',
                PolicyDocument={
                    'Version': '2012-10-17',
                    'Statement': [{
                        'Effect': 'Allow',
                        'Action': ['s3:ListBucket', 's3:GetObject', 's3:PutObject', 's3:GetBucketLocation'],
                        'Resource': [s3_bucket_arn, f'{s3_bucket_arn}/*'],
                    }],
                },
            ),
            Policy(  # CloudWatch Logs: only CodeBuild's own log groups
                PolicyName='CBLogsAccess',
                PolicyDocument={
                    'Version': '2012-10-17',
                    'Statement': [{
                        'Effect': 'Allow',
                        'Action': ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
                        'Resource': [log_group_arn, log_stream_arn],
                    }],
                },
            ),
            Policy(  # ECR: auth token (account-level) + push/pull on the repos being built
                PolicyName='CBECRAccess',
                PolicyDocument={
                    'Version': '2012-10-17',
                    'Statement': [
                        {'Effect': 'Allow', 'Action': ['ecr:GetAuthorizationToken'], 'Resource': ['*']},
                        {
                            'Effect': 'Allow',
                            'Action': [
                                'ecr:BatchCheckLayerAvailability',
                                'ecr:GetDownloadUrlForLayer',
                                'ecr:BatchGetImage',
                                'ecr:PutImage',
                                'ecr:InitiateLayerUpload',
                                'ecr:UploadLayerPart',
                                'ecr:CompleteLayerUpload',
                            ],
                            'Resource': repo_arns,
                        },
                    ],
                },
            ),
            Policy(  # CodeBuild test/coverage reports for this account's report groups
                PolicyName='CBReportAccess',
                PolicyDocument={
                    'Version': '2012-10-17',
                    'Statement': [{
                        'Effect': 'Allow',
                        'Action': [
                            'codebuild:CreateReportGroup',
                            'codebuild:CreateReport',
                            'codebuild:UpdateReport',
                            'codebuild:BatchPutTestCases',
                            'codebuild:BatchPutCodeCoverages',
                        ],
                        'Resource': [report_group_arn],
                    }],
                },
            ),
        ]

    # Falcon secret ARNs (env-scoped, owned by appconfig).
    _FALCON_EXPORTS = (
        C4AppConfigExports.EXPORT_FALCON_CID,
        C4AppConfigExports.EXPORT_FALCON_CLIENT_ID,
        C4AppConfigExports.EXPORT_FALCON_CLIENT_SECRET,
    )

    def cb_external_secrets_policy(self, *, include_dockerhub=True, include_falcon=False) -> Policy:
        """ Grants the CodeBuild role read access (GetSecretValue, DescribeSecret) on the
            DockerHub secret (owned by the ecosystem-scoped shared_secrets stack) and the
            Falcon secrets (owned by the per-env appconfig stack). Importing the ARNs via
            cross-stack ImportValue keeps this stack from owning sensitive material. """
        dockerhub_arn = self.SHARED_SECRETS_EXPORTS.import_value(
            C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS)
        resources = [dockerhub_arn] if include_dockerhub else []
        if include_falcon:
            resources += [self.APPCONFIG_EXPORTS.import_value(export) for export in self._FALCON_EXPORTS]
        return Policy(
            PolicyName='CBExternalSecretsAccess',
            PolicyDocument={
                'Version': '2012-10-17',
                'Statement': [{
                    'Effect': 'Allow',
                    'Action': ['secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret'],
                    'Resource': resources,
                }],
            },
        )

    def cb_dockerhub_env_vars(self) -> list:
        """ SECRETS_MANAGER-typed DockerHub env vars CodeBuild expands at build start, used for
            `docker login` to avoid DockerHub pull rate limits. The DockerHub secret is JSON-shaped
            so the env var Value is `<arn>:<json-key>`:
              echo "$DOCKERHUB_TOKEN" | docker login -u "$DOCKERHUB_USERNAME" --password-stdin
        """
        dockerhub_arn = self.SHARED_SECRETS_EXPORTS.import_value(
            C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS)
        return [
            {'Name': 'DOCKERHUB_USERNAME', 'Type': 'SECRETS_MANAGER',
             'Value': Join(':', [dockerhub_arn, self.DOCKERHUB_SECRET_USERNAME_KEY])},
            {'Name': 'DOCKERHUB_TOKEN', 'Type': 'SECRETS_MANAGER',
             'Value': Join(':', [dockerhub_arn, self.DOCKERHUB_SECRET_TOKEN_KEY])},
        ]

    def cb_falcon_env_vars(self) -> list:
        """ SECRETS_MANAGER-typed Crowdstrike Falcon env vars, needed ONLY by the build that
            produces the falcon-sensor image. The Falcon secrets are plain strings so the Value is
            just `<arn>`. These are the sensitive API client credentials, so they must not be
            handed to unrelated builds (e.g. the third-party xTea external-pipeline build) — see
            SEC-12. """
        return [
            {'Name': 'FALCON_CID', 'Type': 'SECRETS_MANAGER',
             'Value': self.APPCONFIG_EXPORTS.import_value(C4AppConfigExports.EXPORT_FALCON_CID)},
            {'Name': 'FALCON_CLIENT_ID', 'Type': 'SECRETS_MANAGER',
             'Value': self.APPCONFIG_EXPORTS.import_value(C4AppConfigExports.EXPORT_FALCON_CLIENT_ID)},
            {'Name': 'FALCON_CLIENT_SECRET', 'Type': 'SECRETS_MANAGER',
             'Value': self.APPCONFIG_EXPORTS.import_value(C4AppConfigExports.EXPORT_FALCON_CLIENT_SECRET)},
        ]

    def cb_env(self, *, include_dockerhub: bool = False, include_falcon: bool = False) -> list:
        """ Assemble the external-secret env vars a project should receive. Projects opt in to
            exactly the secrets they need rather than every project getting all five (SEC-12). """
        env = []
        if include_dockerhub:
            env += self.cb_dockerhub_env_vars()
        if include_falcon:
            env += self.cb_falcon_env_vars()
        return env

    @staticmethod
    def cb_artifacts() -> Artifacts:
        """ Configure with no artifacts - while artifacts are useful for optimizing build time,
            we are most interested in having the most up-to-date versions on every build.
        """
        return Artifacts(Type='NO_ARTIFACTS')

    def cb_portal_environment_vars(self, repo_name=None, image_tag=None) -> Environment:
        """ Environment configuration for the portal build """
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            Image=self.BUILD_IMAGE,
            EnvironmentVariables=[
                {'Name': 'AWS_DEFAULT_REGION', 'Value': REGION},
                {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
                # main is the default repo name, only needs override in blue/green
                {'Name': 'IMAGE_REPO_NAME', 'Value': self.DEFAULT_ECR_REPO_NAME if not repo_name else repo_name},
                {'Name': 'IMAGE_TAG',
                 'Value': image_tag if image_tag else ConfigManager.get_config_setting(
                     Settings.ECS_IMAGE_TAG, default='latest'
                 )},
            ] + self.cb_env(include_dockerhub=True),  # portal build pulls base images from DockerHub
            Type=self.BUILD_TYPE,
            PrivilegedMode=True
        )

    def cb_pipeline_environment_vars(self) -> Environment:
        """ Environment configuration for the pipeline builds """
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            Image=self.BUILD_IMAGE,
            EnvironmentVariables=[
                {'Name': 'AWS_DEFAULT_REGION', 'Value': REGION},
                {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
                {'Name': 'IMAGE_REPO_NAME', 'Value': 'base'},  # default to base, override by caller
                {'Name': 'IMAGE_TAG',  # Use standard default version as of now, no locked version to resolve
                 'Value': self.DEFAULT_PIPELINE_DEPLOY_BRANCH},
                {'Name': 'BUILD_PATH', 'Value': 'cgap-pipeline-base/dockerfiles/base'}  # default to base, override by caller
            # First-party pipeline build produces the falcon-sensor image, so it gets Falcon creds.
            ] + self.cb_env(include_dockerhub=True, include_falcon=True),
            Type=self.BUILD_TYPE,
            PrivilegedMode=True
        )

    def cb_external_pipeline_environment_vars(self) -> Environment:
        """ Environment configuration for the external pipeline builds """
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            Image=self.BUILD_IMAGE,
            EnvironmentVariables=[
                {'Name': 'AWS_DEFAULT_REGION', 'Value': REGION},
                {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
                {'Name': 'IMAGE_REPO_NAME', 'Value': 'xtea_germline'},  # default to xtea, override by caller
                {'Name': 'IMAGE_TAG',  # Use standard default version as of now, no locked version to resolve
                 'Value': self.DEFAULT_EXTERNAL_GITHUB_PIPELINE_BRANCH},
                {'Name': 'BUILD_PATH', 'Value': 'xTea-germline/dockerfiles/xtea_germline'}
            # Third-party (xTea) build: DockerHub pull creds only, NEVER the Falcon creds (SEC-12).
            ] + self.cb_env(include_dockerhub=True),
            Type=self.BUILD_TYPE,
            PrivilegedMode=True
        )

    def cb_tibanna_environment_vars(self) -> Environment:
        """ Environment configuration for tibanna """
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            Image=self.BUILD_IMAGE,
            EnvironmentVariables=[
                {'Name': 'AWS_DEFAULT_REGION', 'Value': REGION},
                {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
                {'Name': 'IMAGE_TAG', 'Value': tibanna_version}  # default to locked version
            # Tibanna build pulls base images from DockerHub but does not build falcon-sensor.
            ] + self.cb_env(include_dockerhub=True),
            Type=self.BUILD_TYPE,
            PrivilegedMode=True
        )

    @staticmethod
    def cb_source_credential() -> SourceCredential:
        """ Grabs a Github Personal Access Token for use with CodeBuild """
        return SourceCredential(
            'GithubSourceCredential',
            AuthType='PERSONAL_ACCESS_TOKEN',
            ServerType='GITHUB',
            Token=ConfigManager.get_config_secret(Secrets.GITHUB_PERSONAL_ACCESS_TOKEN)
        )

    def cb_source(self, *, github_repo_url) -> Source:
        """ Defines the source for the code build job, typically Github """
        return Source(
            Auth=SourceAuth(
                Resource=Ref(self.cb_source_credential()),
                Type='OAUTH'
            ),
            Location=github_repo_url,
            Type='GITHUB',
            GitSubmodulesConfig=GitSubmodulesConfig(
                FetchSubmodules=True
            )
        )

    @staticmethod
    def uses_srce_network():
        """CodeBuild keeps its stack identity; IT-provided Application VPC selects its network."""
        return bool(ConfigManager.get_config_setting(Settings.VPC_ID, default=None))

    def cb_vpc_config(self) -> VpcConfig:
        """Use exports from exactly one Application VPC, never the DB/Compute VPCs."""
        exports = self.NETWORK_EXPORTS
        if self.uses_srce_network():
            exports = C4SRCENetworkExports()
            exports.get_subnet_ids()  # offline validation of required/disjoint Application subnets
        return VpcConfig(
            SecurityGroupIds=[exports.import_value(exports.APPLICATION_SECURITY_GROUP)],
            Subnets=[exports.import_value(exports.PRIVATE_SUBNETS[0])],
            VpcId=exports.import_value(exports.VPC)
        )

    def cb_project(self, *, project_name, github_repo_url, branch, environment, iam_role) -> Project:
        """ Builds a CodeBuild project for project_name """
        return Project(
            camelize(project_name),
            Artifacts=self.cb_artifacts(),
            Description=f'Build project for {project_name}',
            Environment=environment,
            LogsConfig=self.cb_logs_config(project_name=project_name),
            Name=project_name,
            ServiceRole=GetAtt(iam_role, 'Arn'),
            Source=self.cb_source(github_repo_url=github_repo_url),
            SourceVersion=branch,
            VpcConfig=self.cb_vpc_config(),
            Tags=self.tags.cost_tag_obj()
        )

    def cb_log_group(self, *, project_name) -> LogGroup:
        """ Managed CloudWatch log group for a CodeBuild project so retention is enforced.
            Uses the same `/aws/codebuild/<project>` path that CodeBuild auto-creates by default —
            on first deploy of this stack against an account where these projects already ran,
            the auto-created log groups must be deleted (or imported) to avoid CFN AlreadyExists. """
        retention = ConfigManager.get_config_setting(
            Settings.CODEBUILD_LOG_RETENTION_DAYS, default=self.DEFAULT_LOG_RETENTION_DAYS)
        return LogGroup(
            f'CodeBuildLogGroupFor{camelize(project_name)}',
            LogGroupName=f'/aws/codebuild/{project_name}',
            RetentionInDays=int(retention),
        )

    @staticmethod
    def cb_logs_config(*, project_name) -> LogsConfig:
        """ Pin CodeBuild stdout/stderr to a known CloudWatch log group. """
        return LogsConfig(
            CloudWatchLogs=CloudWatchLogs(
                Status='ENABLED',
                GroupName=f'/aws/codebuild/{project_name}',
            )
        )

    def output_value(self, resource, export_name) -> Output:
        """ Outputs resource value given an export name """
        # TODO: refactor this method for general use
        logical_id = self.name.logical_id(export_name)
        return Output(
            camelize(logical_id),
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name)
        )
