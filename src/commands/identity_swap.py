import argparse
from ..base import ConfigManager
from dcicutils.beanstalk_utils import _create_foursight_new
from dcicutils.ecs_utils import ECSUtils


def identity_swap(*, blue, green):
    """ Triggers an ECS Service update for the blue and green clusters,
        swapping their tasks"""
    # resolve respective ECS clusters, services
    # match up services
    # swap the task definitions
    pass


def main():
    parser = argparse.ArgumentParser(description='Does an in-place task swap for all services in the given two envs.')
    parser.add_argument('blue', help='First env we are swapping', type=str)
    parser.add_argument('green', help='Second env we are swapping', type=str)
    args = parser.parse_args()

    with ConfigManager.validate_and_source_configuration():
        identity_swap(blue=args.blue, green=args.green)


if __name__ == '__main__':
    main()
