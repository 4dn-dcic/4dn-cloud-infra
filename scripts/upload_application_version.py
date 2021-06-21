from dcicutils.docker_utils import DockerUtils
from dcicutils.ecr_utils import ECRUtils

# TODO: This script can maybe go away. -kmp&will 21-Jun-2021

# TODO: populate from config
# Name of the environment we are creating
ENV_NAME = 'cgap-mastertest'

# Path to the production image (for now, this is my local path) - Will
PATH_TO_BUILD_DIR = '/Users/willronchetti/Documents/4dn/cgap-portal2/deploy/docker/production'

# Tag you want to upload to ECR
TAG = 'latest'


def get_config():
    pass  # grab the above info (at least)


def authenticate_docker_with_ecr(docker_utils, ecr_utils):
    """ Authenticates the docker_client with ECR. """
    ecr_utils.resolve_repository_uri()
    auth_info = ecr_utils.authorize_user()
    ecr_pass = ecr_utils.extract_ecr_password_from_authorization(
        authorization=auth_info)
    docker_utils.login(ecr_repo_uri=auth_info['proxyEndpoint'],
                       ecr_user='AWS',
                       ecr_pass=ecr_pass)
    return ecr_pass


def build_tag_push_image_to_ecr(docker_utils, ecr_utils, ecr_pass):
    """ Once logged in using ECR creds above, can trigger build/tag/push. """
    image, build_log = docker_utils.build_image(path=PATH_TO_BUILD_DIR, tag=TAG)
    docker_utils.tag_image(image=image, tag=TAG, ecr_repo_name=ecr_utils.get_uri())
    docker_utils.push_image(tag=TAG, ecr_repo_name=ecr_utils.get_uri(),
                            auth_config={
                                'username': 'AWS',
                                'password': ecr_pass
                            })


def main():
    """ Intended to be invoked via Make target - note that this will take 15 minutes+ to run """
    docker_utils = DockerUtils()
    ecr_utils = ECRUtils(env_name=ENV_NAME, local_repository='cgap-local')
    ecr_pass = authenticate_docker_with_ecr(docker_utils, ecr_utils)
    build_tag_push_image_to_ecr(docker_utils, ecr_utils, ecr_pass)


if __name__ == '__main__':
    main()
