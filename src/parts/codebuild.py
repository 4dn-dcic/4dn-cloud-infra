from troposphere import Template, Parameter, AccountId
from troposphere.codebuild import Artifacts, Environment, Project, Source
from .network import C4NetworkExports
from ..part import C4Part
from ..base import ConfigManager, Settings


class C4CodeBuild(C4Part):
    DEFAULT_COMPUTE_TYPE = 'BUILD_GENERAL1_SMALL'
    STACK_NAME_TOKEN = 'codebuild'
    STACK_TITLE_TOKEN = 'CodeBuild'
    NETWORK_EXPORTS = C4NetworkExports()

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        return template

    @staticmethod
    def cb_artifacts():
        return Artifacts(Type="NO_ARTIFACTS")

    @staticmethod
    def _cb_base_environment_vars():
        return [
            {'Name': 'AWS_DEFAULT_REGION', 'Value': 'us-east-1'},
            {'Name': 'AWS_ACCOUNT_ID', 'Value': AccountId},
            {'Name': 'IMAGE_REPO_NAME', 'Value': ConfigManager.get_config_setting(Settings.ENV_NAME)},
            {'Name': 'IMAGE_TAG', 'Value': ConfigManager.get_config_setting(Settings.ECS_IMAGE_TAG, default='latest')}
        ]

    def cb_environment_portal(self):
        return Environment(
            ComputeType=self.DEFAULT_COMPUTE_TYPE,
            EnvironmentVariables=self._cb_base_environment_vars()
        )
