from ..constants import Settings
from .network import C4NetworkExports
from .ec2_common import C4EC2Common


class C4JupyterHubSupport(C4EC2Common):
    """
    Layer that provides a Load Balancer + EC2 instance for running our Dockerized JH component.
    The LB + EC2 template is inherited from C4EC2Common.build_template; only the driving attributes
    and generate_user_data() below vary (RED-5).
    """
    STACK_NAME_TOKEN = 'jupyterhub'
    STACK_TITLE_TOKEN = 'Jupyterhub'
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_INSTANCE_SIZE = 'c5.large'
    IDENTIFIER = 'JupyterHub'
    SSH_KEY_SETTING = Settings.JH_SSH_KEY
    INSTANCE_SIZE_SETTING = Settings.JH_INSTANCE_SIZE
    # HEALTH_CHECK_PATH unset -> use C4EC2Common.lbv2_target_group's default health path

    def generate_user_data(self):
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
