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
    ENV_NAME = 'ENCODED_ENV_NAME'  # probably should just be 'env.name'

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


# dmichaels/2022-06-06: Factored out from base.py.
COMMON_STACK_PREFIX = "c4-"
COMMON_STACK_PREFIX_CAMEL_CASE = "C4"


# dmichaels/2022-06-06: Factored out from datastore.py.
class C4DatastoreBase:
    """
    Factored out of C4Datastore to to generate names before orchestration (e.g. init-custom-dir).
    """
    STACK_NAME_TOKEN = "datastore"
    STACK_TITLE_TOKEN = "Datastore"
    APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX = 'ApplicationConfiguration'
    RDS_SECRET_NAME_SUFFIX = 'RDSSecret'  # Used as logical id suffix in resource names

# dmichaels/2022-06-22: Factored out from StackNameMixin in part.py.
class StackNameMixinBase:
    SHARING = 'env'
    def SHARING_QUALIFIERS(env_name: str, ecosystem: str):
        _SHARING_QUALIFIERS = {
            'env': f"{env_name}",
            'ecosystem': f"{ecosystem}",
            'account': "",
        }
        return _SHARING_QUALIFIERS

# dmichaels/2022-06-22: Factored out from C4IAM in iam.py.
class C4IAMBase:
    """
    Factored out of C4IAM to to generate names before orchestration (e.g. setup-remaining-secrets).
    """
    STACK_NAME_TOKEN = "iam"
    STACK_TITLE_TOKEN = "IAM"
    SHARING = 'ecosystem'


# dmichaels/2022-07-05: Factored out from sentieon.py.
class C4SentieonSupportBase:
    STACK_NAME_TOKEN = 'sentieon'
    STACK_TITLE_TOKEN = 'Sentieon'
