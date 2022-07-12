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
                                                default_key=ssh_key,
                                                user_data=self.generate_higlass_user_data()))

        # Add load balancer for the hub
        template.add_resource(self.lb_security_group(identifier=self.IDENTIFIER))
        target_group = self.lbv2_target_group(identifier=self.IDENTIFIER)
        template.add_resource(target_group)
        template.add_resource(self.application_load_balancer_listener(identifier=self.IDENTIFIER,
                                                                      target_group=target_group))
        template.add_resource(self.application_load_balancer(identifier=self.IDENTIFIER))
        return template

    @staticmethod
    def generate_higlass_user_data():
        """ User data that pulls down the Docker image for a higlass server for use on the instance.
            Note that this assumes an Ubuntu style image!
        """
        return [
            '#!/bin/bash -xe', '\n',
            'sudo apt-get update', '\n',
            'sudo apt-get install apt-transport-https ca-certificates curl software-properties-common git', '\n',
            'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -', '\n',
            'sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"', '\n',
            'sudo apt update', '\n'
            'apt-cache policy docker-ce', '\n',
            'sudo apt install docker-ce awscli', '\n',
            'mkdir hg-data', '\n',
            'mkdir hg-tmp', '\n',
            'aws s3 sync s3://cgap-higlass/hg-data hg-data', '\n',
            'sudo docker pull higlass/higlass-docker', '\n',
            'sudo git clone https://github.com/dbmi-bgm/higlass-docker-setup', '\n',
            'cd higlass-docker-setup', '\n',
            'sudo -E ./start_production.sh'
        ]

