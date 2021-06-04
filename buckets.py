from foursight_core.buckets import Buckets as Buckets_from_core


class Buckets(Buckets_from_core):
    """ Create buckets for foursight """

    prefix = ''
    envs = ['cgap-mastertest']  # XXX: make configurable


def main():
    buckets = Buckets()
    buckets.create_buckets()
    buckets.configure_env_bucket()


if __name__ == '__main__':
    main()
