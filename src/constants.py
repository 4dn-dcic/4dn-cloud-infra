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


class Settings:

    # General constants

    ACCOUNT_NUMBER = 'account_number'
    DEPLOYING_IAM_USER = 'deploying_iam_user'
    ENV_NAME = 'ENCODED_BS_ENV'  # probably should just be 'env.name'

    # We no longer use this setting. Now we do C4DatastoreExports.get_env_bucket()
    # GLOBAL_ENV_BUCKET = 'GLOBAL_ENV_BUCKET'

    IDENTITY = 'identity'  # XXX: import from dcicutils  -- change in progress to put it on health page
    S3_BUCKET_ORG = "s3.bucket.org"  # was 'ENCODED_S3_BUCKET_ORG'
    S3_BUCKET_ECOSYSTEM = "s3.bucket.ecosystem"

    APP_KIND = "app.kind"

    # RDS Configuration Options

    RDS_INSTANCE_SIZE = 'rds.instance_size'
    RDS_STORAGE_SIZE = 'rds.storage_size'
    RDS_STORAGE_TYPE = 'rds.storage_type'
    RDS_DB_NAME = 'rds.db_name'              # parameter default if empty or missing = "ebdb"
    RDS_DB_PORT = 'rds.db_port'              # parameter default if empty or missing = "5432"
    RDS_DB_USERNAME = 'rds.db_username'
    RDS_AZ = 'rds.az'                        # TODO: Ignored for now. Always defaults to "us-east-1"
    RDS_POSTGRES_VERSION = 'rds.postgres_version'

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
    ECS_WSGI_MEMORY = 'ecs.wsgi.memory'
    ECS_INDEXER_COUNT = 'ecs.indexer.count'
    ECS_INDEXER_CPU = 'ecs.indexer.cpu'
    ECS_INDEXER_MEMORY = 'ecs.indexer.memory'
    ECS_INGESTER_COUNT = 'ecs.ingester.count'
    ECS_INGESTER_CPU = 'ecs.ingester.cpu'
    ECS_INGESTER_MEMORY = 'ecs.ingester.memory'
    ECS_DEPLOYMENT_CPU = 'ecs.deployment.cpu'
    ECS_DEPLOYMENT_MEMORY = 'ecs.deployment.memory'
    ECS_INITIAL_DEPLOYMENT_CPU = 'ecs.initial_deployment.cpu'
    ECS_INITIAL_DEPLOYMENT_MEMORY = 'ecs.initial_deployment.memory'

    # Fourfront Specific Options
    FOURFRONT_VPC = 'fourfront.vpc'
    FOURFRONT_VPC_CIDR = 'fourfront.vpc.cidr'
    FOURFRONT_PRIMARY_SUBNET = 'fourfront.vpc.subnet_a'
    FOURFRONT_SECONDARY_SUBNET = 'fourfront.vpc.subnet_b'
    FOURFRONT_RDS_SECURITY_GROUP = 'fourfront.rds.sg'
    FOURFRONT_HTTPS_SECURITY_GROUP = 'fourfront.https.sg'
