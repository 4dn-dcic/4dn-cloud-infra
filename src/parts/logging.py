from troposphere import logs, Template, Output, Ref
from dcicutils.cloudformation_utils import dehyphenate
from ..constants import DeploymentParadigm
from ..base import ConfigManager, Settings, APP_DEPLOYMENT
from ..part import C4Part
from ..exports import C4Exports


class C4LoggingExports(C4Exports):
    """ Contains export for logging layer, just the name of the log group """
    APPLICATION_LOG_GROUP = 'ExportApplicationLogGroup'
    APPLICATION_LOG_GROUP_BLUE = f'ExportApplicationLogGroup{DeploymentParadigm.BLUE.capitalize()}'
    APPLICATION_LOG_GROUP_GREEN = f'ExportApplicationLogGroup{DeploymentParadigm.GREEN.capitalize()}'

    def __init__(self):
        parameter = 'LoggingStackNameParameter'
        super().__init__(parameter)


class C4Logging(C4Part):
    EXPORTS = C4LoggingExports()
    STACK_NAME_TOKEN = 'logging'
    STACK_TITLE_TOKEN = 'Logging'
    SHARING = 'ecosystem'

    def build_template(self, template: Template) -> Template:
        """ Builds the Docker log group and outputs it. Also builds a VPC flow log group.
            Will build 2 if the 'blue/green' deployment setting is on.
        """
        if APP_DEPLOYMENT == DeploymentParadigm.BLUE_GREEN:
            blue_lg = self.build_log_group(
                identifier=f'{dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME))}'
                           f'DockerLogs{DeploymentParadigm.BLUE.capitalize()}',
                retention_in_days=365, deletion_policy='Retain'
            )
            template.add_resource(blue_lg)
            template.add_output(
                self.output_application_log_group(blue_lg, export_name=C4LoggingExports.APPLICATION_LOG_GROUP_BLUE))
            template.add_resource(self.build_log_group(identifier=f'VPCFlowLogs{DeploymentParadigm.BLUE.capitalize()}',
                                                       retention_in_days=365, deletion_policy='Retain'))

            green_lg = self.build_log_group(
                identifier=f'{dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME))}DockerLogs'
                           f'{DeploymentParadigm.GREEN.capitalize()}',
                retention_in_days=365, deletion_policy='Retain')
            template.add_resource(green_lg)
            template.add_output(
                self.output_application_log_group(green_lg, export_name=C4LoggingExports.APPLICATION_LOG_GROUP_GREEN))
            template.add_resource(self.build_log_group(identifier=f'VPCFlowLogs{DeploymentParadigm.GREEN.capitalize()}',
                                                       retention_in_days=365, deletion_policy='Retain'))
        else:
            docker_log_group = self.build_log_group(
                identifier=('CGAPDockerLogs' if ConfigManager.get_config_setting(Settings.APP_KIND) != 'ff'
                            else f'{dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME))}DockerLogs'),
                retention_in_days=365, deletion_policy='Retain'
            )
            template.add_resource(docker_log_group)
            template.add_output(self.output_application_log_group(docker_log_group))
            template.add_resource(self.build_log_group(identifier='VPCFlowLogs',
                                                       retention_in_days=365, deletion_policy='Retain'))
        return template

    def build_log_group(self, identifier: str,
                        retention_in_days: int, deletion_policy='Retain') -> logs.LogGroup:
        """ Builds a log group under the given identifier with the given retention policy. """
        return logs.LogGroup(
            identifier,
            RetentionInDays=retention_in_days,
            DeletionPolicy=deletion_policy,
            Tags=self.tags.cost_tag_obj()
        )

    def output_application_log_group(self, resource: logs.LogGroup, export_name=None) -> Output:
        """ Outputs the application log group. """
        export_name = export_name or C4LoggingExports.APPLICATION_LOG_GROUP
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
