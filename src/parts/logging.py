from troposphere import logs, Template, Output, Ref
from ..part import C4Part
from ..exports import C4Exports


class C4LoggingExports(C4Exports):
    """ Contains export for logging layer, just the name of the log group """
    CGAP_APPLICATION_LOG_GROUP = 'ExportApplicationLogGroup'

    def __init__(self):
        parameter = 'LoggingStackNameParameter'
        super().__init__(parameter)


class C4Logging(C4Part):
    EXPORTS = C4LoggingExports()

    def build_template(self, template: Template) -> Template:
        log_group = logs.LogGroup(
            'CGAPDockerLogs',
            RetentionInDays=365,
            DeletionPolicy='Retain'  # XXX: configure further?
        )
        template.add_resource(log_group)
        template.add_output(self.output_log_group(log_group))
        return template

    def output_log_group(self, resource: logs.LogGroup) -> Output:
        export_name = C4LoggingExports.CGAP_APPLICATION_LOG_GROUP
        logical_id = self.name.logical_id(export_name)
        return Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
