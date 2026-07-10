from ..constants import Settings
from .network import C4NetworkExports
from .ec2_common import C4EC2Common


class C4HiglassServer(C4EC2Common):
    """
    Layer that provides a Load Balancer + EC2 instance for running our Dockerized Higlass component.
    The LB + EC2 template is inherited from C4EC2Common.build_template; only the driving attributes
    and generate_user_data() below vary (RED-5).
    TODO: IAM permissions?
    """
    STACK_NAME_TOKEN = 'higlass'
    STACK_TITLE_TOKEN = 'Higlass'
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_INSTANCE_SIZE = 'c5.large'
    IDENTIFIER = 'Higlass'
    SSH_KEY_SETTING = Settings.HIGLASS_SSH_KEY
    INSTANCE_SIZE_SETTING = Settings.HIGLASS_INSTANCE_SIZE
    HEALTH_CHECK_PATH = '/api/v1/tilesets/'

    def generate_user_data(self):
        """ User data that pulls down the Docker image for a higlass server for use on the instance.
            Note that this assumes an AMD64 arch + Ubuntu style image!
        """
        return [
            '#!/bin/bash -xe', '\n',
            'sudo apt-get update', '\n',
            'sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common git', '\n',
            'curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -', '\n',
            'sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable"', '\n',
            'sudo apt update; apt-cache policy docker-ce', '\n'
            'sudo apt install --assume-yes docker-ce', '\n',
            'mkdir ~/hg-tmp', '\n',
            'curl https://cgap-higlass.s3.amazonaws.com/hg-data/higlass-server-data.tar.gz --output higlass-server-data.tar.gz', '\n',
            'tar -xzvf higlass-server-data.tar.gz --directory ~', '\n',
            'sudo git clone https://github.com/dbmi-bgm/higlass-docker-setup', '\n',
            'cd higlass-docker-setup', '\n',
            'sudo -E ./start_production.sh'
        ]
