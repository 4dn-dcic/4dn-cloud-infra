from troposphere import logs, Template
from src.part import QCPart


class QCLogging(QCPart):

    def build_template(self, template: Template) -> Template:
        log_group = logs.LogGroup(
            'CGAPDockerLogs',
            RetentionInDays=365,
            DeletionPolicy='Retain'  # XXX: configure further?
        )
        template.add_resource(log_group)
        template.add_output(log_group)  # XXX: is this right?
        return template
