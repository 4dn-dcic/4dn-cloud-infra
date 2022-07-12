from troposphere import (
    Template, Parameter,
)

from ..base import ConfigManager, Settings
from .network import C4NetworkExports
from .ec2_common import C4EC2Common


class C4HiglassServer(C4EC2Common):
    """
    Layer that provides a Load Balancer + EC2 instance for running our Dockerized Higlass component.
    """
    STACK_NAME_TOKEN = 'higlass'
    STACK_TITLE_TOKEN = 'Higlass'
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_INSTANCE_SIZE = 'c5.large'
    IDENTIFIER = 'Higlass'

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # SSH Key for access
        ssh_key = self.ssh_key(identifier=self.IDENTIFIER,
                               default=ConfigManager.get_config_setting(Settings.HIGLASS_SSH_KEY))
        template.add_parameter(ssh_key)

        # TODO: ACM certificate parameter?

        template.add_resource(self.application_security_group(identifier=self.IDENTIFIER))
        for rule in self.application_security_rules(identifier=self.IDENTIFIER):
            template.add_resource(rule)

        # JupyterHub instance
        template.add_resource(self.ec2_instance(identifier=self.IDENTIFIER,
                                                instance_size=ConfigManager.get_config_setting(
                                                    Settings.HIGLASS_INSTANCE_SIZE, default=self.DEFAULT_INSTANCE_SIZE
                                                ),
                                                default_key=ssh_key))

        # Add load balancer for the hub
        template.add_resource(self.lb_security_group(identifier=self.IDENTIFIER))
        target_group = self.lbv2_target_group(identifier=self.IDENTIFIER)
        template.add_resource(target_group)
        template.add_resource(self.application_load_balancer_listener(identifier=self.IDENTIFIER,
                                                                      target_group=target_group))
        template.add_resource(self.application_load_balancer(identifier=self.IDENTIFIER))
        return template
