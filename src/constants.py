# This file contains constants mapping to the environment variables
# that contain the desired information. Setting any of these values
# in config.json will have the effect of setting the configuration
# option for the orchestration. The only options listed that are
# currently unavailable are: ES_MASTER_COUNT, ES_MASTER_TYPE

class Secrets:
    """ Secret values pulled from custom/secrets.json follow these identifiers """
    # Secrets (customarily held in environment variables by these names)
    AUTH0_CLIENT = "Auth0Client"
    AUTH0_SECRET = "Auth0Secret"
    ENCODED_SECRET = "ENCODED_SECRET"
    RECAPTCHA_KEY = 'reCaptchaKey'
    RECAPTCHA_SECRET = 'reCaptchaSecret'
    S3_ENCRYPT_KEY = "S3_ENCRYPT_KEY"


class DeploymentParadigm:
    """ Application level deployment paradigm - either standalone or blue/green.
        blue/green is not supported by CGAP. standalone is supported by both.
    """
    STANDALONE = 'standalone'
    BLUE_GREEN = 'blue/green'
    BLUE = 'blue'
    GREEN = 'green'


class Settings:
    """ Config values pulled from custom/config.json follow these identifiers """

    # General constants

    ACCOUNT_NUMBER = 'account_number'
    DEPLOYING_IAM_USER = 'deploying_iam_user'
    ENV_NAME = 'ENCODED_BS_ENV'  # probably should just be 'env.name'

    # We no longer use this setting. Now we do C4DatastoreExports.get_env_bucket()
    # GLOBAL_ENV_BUCKET = 'GLOBAL_ENV_BUCKET'

    IDENTITY = 'identity'  # XXX: import from dcicutils  -- change in progress to put it on health page
    BLUE_IDENTITY = 'blue.identity'
    GREEN_IDENTITY = 'green.identity'
    S3_BUCKET_ORG = 's3.bucket.org'  # was 'ENCODED_S3_BUCKET_ORG'
    S3_BUCKET_ECOSYSTEM = 's3.bucket.ecosystem'
    S3_BUCKET_ENCRYPTION = 's3.bucket.encryption'

    APP_KIND = 'app.kind'
    APP_DEPLOYMENT = 'app.deploy'

    # RDS Configuration Options

    RDS_INSTANCE_SIZE = 'rds.instance_size'
    RDS_STORAGE_SIZE = 'rds.storage_size'
    RDS_STORAGE_TYPE = 'rds.storage_type'
    RDS_DB_NAME = 'rds.db_name'              # parameter default if empty or missing = "ebdb"
    RDS_DB_PORT = 'rds.db_port'              # parameter default if empty or missing = "5432"
    RDS_DB_USERNAME = 'rds.db_username'
    RDS_AZ = 'rds.az'                        # TODO: Ignored for now. Always defaults to "us-east-1"
    RDS_POSTGRES_VERSION = 'rds.postgres_version'
    RDS_NAME = 'rds.name'  # can be used to configure name of RDS instance, foursight must know it - Will Nov 2 2021

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

    # Foursight options
    FOURSIGHT_ES_URL = 'foursight.es_url'
    FOURSIGHT_APP_VERSION_BUCKET = 'foursight.application_version_bucket'

    # Sentieon Options
    SENTIEON_SSH_KEY = 'sentieon.ssh_key'

    # JH Options
    JH_SSH_KEY = 'jupyterhub.ssh_key'
    JH_INSTANCE_SIZE = 'jupyterhub.instance_size'

    # Secure AMI
    HMS_SECURE_AMI = 'hms.secure_ami'

    # S3 KMS ServerSide Encryption Key
    S3_ENCRYPT_KEY_ID = 's3.encrypt_key_id'


# dmichaels/2022-06-06
# Factored out COMMON_STACK_PREFIX and COMMON_STACK_PREFIX_CAMEL_CASE from base.py.
# This is so we can use in (new) get_suggest_stack_name in names.py,
# which (both init-custom-dir and) StackNameMixin.suggest_stack_name() will use.
#
COMMON_STACK_PREFIX = "c4-"
COMMON_STACK_PREFIX_CAMEL_CASE = "C4"

# dmichaels/2022-06-06
# Factored out values for STACK_NAME_TOKEN ("datastore") and STACK_TITLE_TOKEN ("Datastore")
# in datastore.py into these DATASTORE_STACK_TITLE_TOKEN and DATASTORE_STACK_NAME_TOKEN;
# different name (with DATASTORE_ prefix) because defined in StackNameMixin in part.py
# This is so we can use in (new) get_global_application_configuration_secret_name in names.py,
# which (both init-custom-dir and) C4Datastore.application_configuration_secret() will use.
#
DATASTORE_STACK_NAME_TOKEN = "datastore"
DATASTORE_STACK_TITLE_TOKEN = "Datastore"

# dmichaels/2022-06-06
# Factored out APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX from C4Datastore in datastore.py;
# different name for clarity (with DATASTORE_ prefix to indicate from C4Datastore class).
# This is so we can use in (new) get_global_application_configuration_secret_name in names.py,
# which (both init-custom-dir and) C4Datastore.application_configuration_secret() will use.
#
DATASTORE_APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX = 'ApplicationConfiguration'
