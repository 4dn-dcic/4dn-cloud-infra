# This file contains constants mapping to the environment variables
# that contain the desired information. Setting any of these values
# in config.json will have the effect of setting the configuration
# option for the orchestration. The only options listed that are
# currently unavailable are: ES_MASTER_COUNT, ES_MASTER_TYPE, IDENTITY

class Secrets:
    # Secrets (customarily held in environment variables by these names)
    AUTH0_CLIENT = "Auth0Client"
    AUTH0_SECRET = "Auth0Secret"
    ENCODED_SECRET = "ENCODED_SECRET"
    RECAPTCHA_KEY = 'reCaptchaKey'
    RECAPTCHA_SECRET = 'reCaptchaSecret'
    S3_ENCRYPT_KEY = "S3_ENCRYPT_KEY"


# AUTH0_CLIENT = Secrets.AUTH0_CLIENT
# AUTH0_SECRET = Secrets.AUTH0_SECRET
# ENCODED_SECRET = Secrets.ENCODED_SECRET
# S3_ENCRYPT_KEY = Secrets.S3_ENCRYPT_KEY


class Settings:

    # General constants

    ACCOUNT_NUMBER = 'account_number'
    DEPLOYING_IAM_USER = 'deploying_iam_user'
    ENV_NAME = 'ENCODED_BS_ENV'  # probably should just be 'env.name'

    # We no longer use this setting. Now we do C4DatastoreExports.get_envs_bucket()
    # GLOBAL_ENV_BUCKET = 'GLOBAL_ENV_BUCKET'

    IDENTITY = 'identity'  # XXX: import from dcicutils
    S3_BUCKET_ORG = "s3.bucket.org"  # was 'ENCODED_S3_BUCKET_ORG'

    # RDS Configuration Options

    RDS_INSTANCE_SIZE = 'rds.instance_size'
    RDS_STORAGE_SIZE = 'rds.storage_size'
    RDS_DB_NAME = 'rds.db_name'              # parameter default if empty or missing = "ebdb"
    RDS_DB_PORT = 'rds.db_port'              # parameter default if empty or missing = "5432"
    RDS_AZ = 'rds.az'                        # TODO: Ignored. Always defaults to "us-east-1"

    # ES Configuration Options

    ES_MASTER_COUNT = 'elasticsearch.master_node_count'
    ES_MASTER_TYPE = 'elasticsearch.master_node_type'
    ES_DATA_COUNT = 'elasticsearch.data_node_count'
    ES_DATA_TYPE = 'elasticsearch.data_node_type'
    ES_VOLUME_SIZE = 'elasticsearch.volume_size'

    # ECS Configuration Options

    ECS_IMAGE_TAG = 'ecs.image_tag'
    ECS_WSGI_COUNT = 'ecs.wsgi.count'
    ECS_WSGI_CPU = 'ecs.wsgi.cpu'
    ECS_WSGI_MEM = 'ecs.wsgi.mem'
    ECS_INDEXER_COUNT = 'ecs.indexer.count'
    ECS_INDEXER_CPU = 'ecs.indexer.cpu'
    ECS_INDEXER_MEM = 'ecs.indexer.mem'
    ECS_INGESTER_COUNT = 'ecs.ingester.count'
    ECS_INGESTER_CPU = 'ecs.ingester.cpu'
    ECS_INGESTER_MEM = 'ecs.ingester.mem'

    # Foursight Configuration Options

    # We now compute the runner in stack.py. -kmp 04-Aug-2021
    # CHECK_RUNNER = 'CHECK_RUNNER'


# ACCOUNT_NUMBER = Settings.ACCOUNT_NUMBER
# CHECK_RUNNER = Settings.CHECK_RUNNER
# DEPLOYING_IAM_USER = Settings.DEPLOYING_IAM_USER
# ECS_IMAGE_TAG = Settings.ECS_IMAGE_TAG
# ECS_INDEXER_COUNT = Settings.ECS_INDEXER_COUNT
# ECS_INDEXER_CPU = Settings.ECS_INDEXER_CPU
# ECS_INDEXER_MEM = Settings.ECS_INDEXER_MEM
# ECS_INGESTER_COUNT = Settings.ECS_INGESTER_COUNT
# ECS_INGESTER_CPU = Settings.ECS_INGESTER_CPU
# ECS_INGESTER_MEM = Settings.ECS_INGESTER_MEM
# ECS_WSGI_COUNT = Settings.ECS_WSGI_COUNT
# ECS_WSGI_CPU = Settings.ECS_WSGI_CPU
# ECS_WSGI_MEM = Settings.ECS_WSGI_MEM
# ENV_NAME = Settings.ENV_NAME
# ES_DATA_COUNT = Settings.ES_DATA_COUNT
# ES_DATA_TYPE = Settings.ES_DATA_TYPE
# ES_MASTER_COUNT = Settings.ES_MASTER_COUNT
# ES_MASTER_TYPE = Settings.ES_MASTER_TYPE
# ES_VOLUME_SIZE = Settings.ES_VOLUME_SIZE
# GLOBAL_ENV_BUCKET = Settings.GLOBAL_ENV_BUCKET
# IDENTITY = Settings.IDENTITY
# RDS_AZ = Settings.RDS_AZ
# RDS_DB_NAME = Settings.RDS_DB_NAME
# RDS_DB_PORT = Settings.RDS_DB_PORT
# RDS_INSTANCE_SIZE = Settings.RDS_INSTANCE_SIZE
# RDS_STORAGE_SIZE = Settings.RDS_STORAGE_SIZE
# S3_BUCKET_ORG = Settings.S3_BUCKET_ORG
