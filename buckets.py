import os
from foursight_core.buckets import Buckets as Buckets_from_core


# TODO: Figure out if this needs to be run at all. Will thinks this will get created by the DataStore stack.
class Buckets(Buckets_from_core):
    """ Create buckets for foursight """

    prefix = ''
    envs = [os.environ.get('ENV_NAME') or 'cgap-mastertest']  # XXX: make configurable


def main():
    buckets = Buckets()
    buckets.create_buckets()
    buckets.configure_env_bucket()


if __name__ == '__main__':
    main()
