from troposphere import (
    Template, Parameter, Ref
)

from ..base import ConfigManager, Settings
from .network import C4NetworkExports
from .ec2_common import C4EC2Common


class C4JupyterHubSupport(C4EC2Common):
    """
    Layer that provides a Load Balancer + EC2 instance for running our Dockerized JH component.
    """
    STACK_NAME_TOKEN = 'jupyterhub'
    STACK_TITLE_TOKEN = 'Jupyterhub'
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_INSTANCE_SIZE = 'c5.large'
    IDENTIFIER = 'JupyterHub'

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # SSH Key for access
        jh_key = ConfigManager.get_config_setting(Settings.JH_SSH_KEY)
        ssh_key = self.ssh_key(identifier=self.IDENTIFIER, default=jh_key)
        template.add_parameter(ssh_key)

        # TODO: ACM certificate parameter?

        # Security Group
        template.add_resource(self.application_security_group(identifier=self.IDENTIFIER))
        for rule in self.application_security_rules(identifier=self.IDENTIFIER):
            template.add_resource(rule)

        # JupyterHub instance
        template.add_resource(self.ec2_instance(identifier=self.IDENTIFIER,
                                                instance_size=ConfigManager.get_config_setting(
                                                    Settings.JH_INSTANCE_SIZE, default=self.DEFAULT_INSTANCE_SIZE
                                                ),
                                                default_key=Ref(ssh_key),
                                                user_data=self.generate_jupyterhub_user_data()))

        # Add load balancer for the hub
        template.add_resource(self.lb_security_group(identifier=self.IDENTIFIER))
        target_group = self.lbv2_target_group(identifier=self.IDENTIFIER)
        template.add_resource(target_group)
        template.add_resource(self.application_load_balancer_listener(identifier=self.IDENTIFIER,
                                                                      target_group=target_group))
        template.add_resource(self.application_load_balancer(identifier=self.IDENTIFIER))
        return template

    @staticmethod
    def generate_jupyterhub_user_data():
        """ User data that does the initial provisioning of the server, but some must be done server side.
            Note that this assumes an AMD64 arch + Ubuntu style image!
            Manual Steps:
                1. chrony provisioning
                2. fuse configuration
                3. .env configuration + source
                4. build and start images
        """
        return [
            '#!/bin/bash -xe', '\n',
            'sudo apt-get update', '\n',
            'sudo apt-get install -y git make supervisor golang-go curl chrony', '\n',
            'curl -O -L http://bit.ly/goofys-latest', '\n',
            'sudo chmod +x /home/ubuntu/goofys-latest', '\n',
            'sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"', '\n',
            'sudo chmod +x /usr/local/bin/docker-compose', '\n',
            'docker-compose --version', '\n',
        ]
