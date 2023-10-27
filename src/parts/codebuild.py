from troposphere import Template, Parameter, AccountId, Join, Region, Ref, Output
from troposphere.codebuild import (
    Artifacts, Environment, Project, Source, SourceAuth, VpcConfig, SourceCredential, GitSubmodulesConfig
)
from troposphere.iam import Role, Policy
from tibanna._version import __version__ as tibanna_version
from dcicutils.cloudformation_utils import camelize
from dcicutils.common import REGION  # note to deploy outside us-east-1 you will need to change this
from .network import C4NetworkExports
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
    DEFAULT_EXTERNAL_GITHUB_PIPELINE_REPOSITORY = 'https://github.com/dbmi-bgm/cgap-pipeline-contribution'
    DEFAULT_TIBANNA_REPOSITORY = 'https://github.com/4dn-dcic/tibanna'
    STACK_NAME_TOKEN = 'codebuild'
    STACK_TITLE_TOKEN = 'CodeBuild'
    DEFAULT_DEPLOY_BRANCH = 'master'
    DEFAULT_PIPELINE_DEPLOY_BRANCH = 'v1.0.0'  # version release tag for cgap-pipeline-main
    DEFAULT_EXTERNAL_GITHUB_PIPELINE_BRANCH = 'v1.0.0'  # TODO: this should be verified
    NETWORK_EXPORTS = C4NetworkExports()
    EXPORTS = C4CodeBuildExports()

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
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
                build_project = self.cb_project(
                    project_name=env_name,
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
            build_project = self.cb_project(
                project_name=portal_env_name,
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
            pipeline_iam_role = self.cb_iam_role(project_name=pipeline_project_name)
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
            pipeline_build_project = self.cb_project(
                project_name=pipeline_project_name,
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
            external_pipeline_build_project = self.cb_project(
                project_name=external_pipeline_project_name,
                github_repo_url=self.DEFAULT_EXTERNAL_GITHUB_PIPELINE_REPOSITORY,
                branch=self.DEFAULT_EXTERNAL_GITHUB_PIPELINE_BRANCH,
                environment=self.cb_external_pipeline_environment_vars()
            )
            template.add_resource(external_pipeline_build_project)
            template.add_output(self.output_value(resource=external_pipeline_build_project,
                                                  export_name=C4CodeBuildExports.output_project_key(
                                                      project_name=external_pipeline_project_name
                                                  )))

        # Build project for Tibanna AWSF
        tibanna_build_project = self.cb_project(
            project_name=tibanna_project_name,
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

    def cb_iam_role(self, *, project_name) -> Role:
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
                self.cb_vpc_policy()
            ],
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/AmazonS3FullAccess',
                'arn:aws:iam::aws:policy/CloudWatchFullAccess',
                'arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess',
                'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser',
            ],
        )

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
            ],
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
            ],
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
            ],
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
            ],
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

    def cb_vpc_config(self) -> VpcConfig:
        """ Configures CB jobs to run in the VPC """
        return VpcConfig(
            SecurityGroupIds=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP)],
            Subnets=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNETS[0])],
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC)
        )

    def cb_project(self, *, project_name, github_repo_url, branch, environment) -> Project:
        """ Builds a CodeBuild project for project_name """
        return Project(
            camelize(project_name),
            Artifacts=self.cb_artifacts(),
            Description=f'Build project for {project_name}',
            Environment=environment,
            Name=project_name,
            ServiceRole=Ref(self.cb_iam_role(project_name=ConfigManager.get_config_setting(Settings.ENV_NAME))),
            Source=self.cb_source(github_repo_url=github_repo_url),
            SourceVersion=branch,
            VpcConfig=self.cb_vpc_config(),
            Tags=self.tags.cost_tag_obj()
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
