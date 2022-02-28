from troposphere import logs, Template, Output, Ref
from dcicutils.cloudformation_utils import dehyphenate
from ..base import ConfigManager, Settings
from ..exports import C4Exports
from .logging import C4Logging


class C4LoggingBGExports(C4Exports):
    """ Contains export for logging layer, just the name of the log group """
    APPLICATION_BLUE_LOG_GROUP = 'ExportBlueApplicationLogGroup'
    APPLICATION_GREEN_LOG_GROUP = 'ExportGreenApplicationLogGroup'

    def __init__(self):
        parameter = 'LoggingStackNameParameter'
        super().__init__(parameter)


class C4BGLogging(C4Logging):
    """ Class that extends normal logging class to build a blue/green version. """

    def build_template(self, template: Template) -> Template:
        """ Builds a logging template with a blue/green copy of Docker logs and VPC
            flow logs.
        """
        blue_log_group = self.build_log_group(
            identifier=f'{dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME))}BlueDockerLogs',
            retention_in_days=365, deletion_policy='Retain'
        )
        green_log_group = self.build_log_group(
            identifier=f'{dehyphenate(ConfigManager.get_config_setting(Settings.ENV_NAME))}GreenDockerLogs',
            retention_in_days=365, deletion_policy='Retain'
        )
        template.add_resource(blue_log_group)
        template.add_resource(green_log_group)
        template.add_output(self.output_application_log_group(
            blue_log_group, export_name=C4LoggingBGExports.APPLICATION_BLUE_LOG_GROUP
        ))
        template.add_output(self.output_application_log_group(
            green_log_group, export_name=C4LoggingBGExports.APPLICATION_GREEN_LOG_GROUP
        ))
        template.add_resource(self.build_log_group(identifier='BlueVPCFlowLogs',
                                                   retention_in_days=365, deletion_policy='Retain'))
        template.add_resource(self.build_log_group(identifier='GreenVPCFlowLogs',
                                                   retention_in_days=365, deletion_policy='Retain'))
        return template

    def output_application_log_group(self, resource: logs.LogGroup, export_name=None) -> Output:
        """ Outputs the application log group, allowing the passing of an export_name. """
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
