from troposphere import Template, Parameter, AccountId, Ref, Output
from troposphere.codebuild import Artifacts, Environment, Project, Source, SourceAuth, VpcConfig
from troposphere.iam import Role, Policy
from .network import C4NetworkExports
from ..part import C4Part
from ..exports import C4Exports
from ..base import ConfigManager, Settings


class C4CodeBuildExports(C4Exports):
    """ Defines export metadata for codebuild """

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
    DEFAULT_COMPUTE_TYPE = 'BUILD_GENERAL1_SMALL'
    BUILD_TYPE = 'LINUX_CONTAINER'
    STACK_NAME_TOKEN = 'codebuild'
    STACK_TITLE_TOKEN = 'CodeBuild'
    DEFAULT_DEPLOY_BRANCH = 'master'
    NETWORK_EXPORTS = C4NetworkExports()
    EXPORTS = C4CodeBuildExports()

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        project_name = ConfigManager.get_config_setting(Settings.ENV_NAME)

        # IAM role for cb
        iam_role = self.cb_iam_role(project_name=project_name)
        template.add_resource(iam_role)

        # Build project
        build_project = self.cb_project(
            project_name=project_name,
            github_repo_url=ConfigManager.get_config_setting(Settings.CODEBUILD_REPOSITORY_URL),
            branch=ConfigManager.get_config_setting(Settings.CODEBUILD_DEPLOY_BRANCH,
                                                    default=self.DEFAULT_DEPLOY_BRANCH)
        )
        template.add_resource(build_project)

        # output build project name, iam role
        template.add_output(self.output_value(resource=build_project,
                                              export_name=C4CodeBuildExports.output_project_key(
                                                  project_name=project_name
                                              )))
        template.add_output(self.output_value(resource=iam_role,
                                              export_name=C4CodeBuildExports.output_project_iam_role(
                                                  project_name=project_name
                                              )))

        return template

    @staticmethod
    def cb_iam_role(*, project_name) -> Role:
        return Role(
            f'CodeBuildRoleFor{project_name}',
            AssumeRolePolicyDocument=Policy(
                Statement=[
                    dict(
                        Effect='Allow',
                        Action=['AssumeRole'],
                        Principal=dict(Service=['codebuild.amazonaws.com'])
                    )
                ]
            ),
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/AmazonS3FullAccess',
                'arn:aws:iam::aws:policy/CloudWatchFullAccess',
                'arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess',
                'arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser'
            ],
        )

    @staticmethod
    def cb_artifacts() -> Artifacts:
        """ Configure with no artifacts - while artifacts are useful for optimizing build time,
            we are most interested in having the most up-to-date versions on every build.
        """
        return Artifacts(Type='NO_ARTIFACTS')

    @staticmethod
    def _cb_base_environment_vars() -> list:
        return [
            {'Name': 'AWS_DEFAULT_REGION', 'Value': 'us-east-1'},
            {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
            {'Name': 'IMAGE_REPO_NAME', 'Value': ConfigManager.get_config_setting(Settings.ENV_NAME)},
            {'Name': 'IMAGE_TAG', 'Value': ConfigManager.get_config_setting(Settings.ECS_IMAGE_TAG, default='latest')}
        ]

    def cb_environment(self) -> Environment:
        """ Environment configuration for the codebuild job """
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            EnvironmentVariables=self._cb_base_environment_vars(),
            Type=self.BUILD_TYPE
        )

    @staticmethod
    def cb_source(*, github_repo_url) -> Source:
        """ Defines the source for the code build job, typically Github """
        return Source(
            Auth=SourceAuth(Type='OAUTH'),
            Location=github_repo_url,
            Type='GITHUB'
        )

    def cb_vpc_config(self) -> VpcConfig:
        """ Configures CB jobs to run in the VPC """
        return VpcConfig(
            SecurityGgroupIds=self.NETWORK_EXPORTS.import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP),
            Subnets=self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNETS[0]),
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC)
        )

    def cb_project(self, *, project_name, github_repo_url, branch) -> Project:
        """ Builds a CodeBuild project for project_name """
        return Project(
            project_name,
            Artifacts=self.cb_artifacts(),
            Description=f'Build project for {project_name}',
            Environment=self.cb_environment(),
            Name=project_name,
            ServiceRole=Ref(self.cb_iam_role(project_name=project_name)),
            Source=self.cb_source(github_repo_url=github_repo_url),
            SourceVersion=branch,
            VpcConfig=self.cb_vpc_config(),
            Tags=self.tags.cost_tag_array()
        )

    def output_value(self, resource, export_name) -> Output:
        """ Outputs resource value given an export name """
        # TODO: refactor this method for general use
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name)
        )
