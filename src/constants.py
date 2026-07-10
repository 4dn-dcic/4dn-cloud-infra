# This file contains constants mapping to the environment variables
# that contain the desired information. Setting any of these values
# in config.json will have the effect of setting the configuration
# option for the orchestration. The only options listed that are
# currently unavailable are: ES_MASTER_COUNT, ES_MASTER_TYPE

class Secrets:
    """ Secret values pulled from custom/secrets.json follow these identifiers """
    # Secrets (customarily held in environment variables by these names)
    AUTH0_DOMAIN = 'Auth0Domain'
    AUTH0_CLIENT = 'Auth0Client'
    AUTH0_SECRET = 'Auth0Secret'
    AUTH0_ALLOWED_CONNECTIONS = 'Auth0AllowedConnections'
    ENCODED_SECRET = 'ENCODED_SECRET'
    RECAPTCHA_KEY = 'reCaptchaKey'
    RECAPTCHA_SECRET = 'reCaptchaSecret'
    S3_ENCRYPT_KEY = 'S3_ENCRYPT_KEY'
    GITHUB_PERSONAL_ACCESS_TOKEN = 'GITHUB_PERSONAL_ACCESS_TOKEN'
    GA4_API_SECRET = 'GA4_API_SECRET'


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
    ADMIN_USERS = 'ENCODED_ADMIN_USERS'  # for customizing the user inserts
    DATA_SET = 'ENCODED_DATA_SET'  # to trigger custom insert load
    GLOBAL_ENV_BUCKET = 'GLOBAL_ENV_BUCKET'  # configure name of ecosystem bucket

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

    # Network options
    SUBNET_PAIR_COUNT = 'subnet.pair_count'

    # Optional bastion host in the standard network stack. Disabled unless bastion.enabled is
    # truthy AND both an AMI and SSH key are configured; a missing key skips the resource rather
    # than raising (see SEC-3).
    BASTION_ENABLED = 'network.bastion.enabled'
    BASTION_AMI = 'network.bastion.ami'
    BASTION_SSH_KEY = 'network.bastion.ssh_key'

    # VPC flow logs on the standard network stack (SEC-9). Enabled by default; set to a falsy
    # value to skip creating the flow log + its CloudWatch log group.
    NETWORK_FLOW_LOGS_ENABLED = 'network.flow_logs.enabled'
    NETWORK_FLOW_LOGS_RETENTION_DAYS = 'network.flow_logs.retention_days'

    # Optional ALB access logs (SEC-9). When alb.access_logs_bucket names a pre-existing S3 bucket
    # (with the required ELB log-delivery bucket policy), the portal ALB writes access logs to it.
    ALB_ACCESS_LOGS_BUCKET = 'alb.access_logs_bucket'
    ALB_ACCESS_LOGS_PREFIX = 'alb.access_logs_prefix'

    # ACM certificate ARN for the portal load balancer (SEC-5). When set, the ALB gets an HTTPS:443
    # listener (with a modern SslPolicy) and HTTP:80 redirects to it; the portal URL is emitted as
    # https://. When unset, the ALB keeps the plain HTTP:80 listener (unchanged behavior).
    ECS_LB_CERTIFICATE_ARN = 'ecs.lb_certificate_arn'

    # Application VPC (ECS portal + foursight) — used in SRCE deployments
    VPC_ID = 'vpc.id'
    VPC_CIDR = 'vpc.cidr'
    PUBLIC_SUBNETS = 'public.subnets'
    PRIVATE_SUBNETS = 'private.subnets'

    # Database VPC (RDS, OpenSearch, Redis) — used in SRCE deployments
    DB_VPC_ID = 'db.vpc.id'
    DB_VPC_CIDR = 'db.vpc.cidr'
    DB_PRIVATE_SUBNETS = 'db.private.subnets'

    # Compute VPC (Sentieon, JupyterHub, Higlass) — used in SRCE deployments
    COMPUTE_VPC_ID = 'compute.vpc.id'
    COMPUTE_VPC_CIDR = 'compute.vpc.cidr'
    COMPUTE_PRIVATE_SUBNETS = 'compute.private.subnets'

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
    RDS_BACKUP_RETENTION = 'rds.backup_retention_days'  # default 7 days

    # ES Configuration Options
    # (master-node options removed as dead/unimplemented -- RED-7)
    ES_DATA_COUNT = 'elasticsearch.data_node_count'
    ES_DATA_TYPE = 'elasticsearch.data_node_type'
    ES_VOLUME_SIZE = 'elasticsearch.volume_size'

    # Redis Configuration Options
    REDIS_ENGINE_VERSION = 'redis.version'
    REDIS_NODE_COUNT = 'redis.node_count'
    REDIS_NODE_TYPE = 'redis.node_type'

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
    FOURSIGHT_CHECK_RUNNER = 'foursight.check_runner'  # for use with FF
    FOURSIGHT_APP_NAME = 'foursight.app_name'  # so can be different from ENV_NAME

    # Sentieon Options
    SENTIEON_SSH_KEY = 'sentieon.ssh_key'
    # CIDR allowed to SSH into the Sentieon license server (institutional VPN/admin range).
    # Defaults to the VPC CIDR (never 0.0.0.0/0) if unset (see SEC-4).
    SENTIEON_ADMIN_CIDR = 'sentieon.admin_cidr'

    # JH Options
    JH_SSH_KEY = 'jupyterhub.ssh_key'
    JH_INSTANCE_SIZE = 'jupyterhub.instance_size'

    # Higlass Options
    HIGLASS_SSH_KEY = 'higlass.ssh_key'
    HIGLASS_INSTANCE_SIZE = 'higlass.instance_size'

    # Secure AMI
    HMS_SECURE_AMI = 'hms.secure_ami'

    # S3 KMS ServerSide Encryption Key
    S3_ENCRYPT_KEY_ID = 's3.encrypt_key_id'

    # CodeBuild options
    CODEBUILD_GITHUB_REPOSITORY_URL = 'codebuild.repo_url'  # url to github source repository
    CODEBUILD_DEPLOY_BRANCH = 'codebuild.build_branch'
    # (CODEBUILD_REPO_NAME removed as dead -- unused by code -- RED-7)
    CODEBUILD_LOG_RETENTION_DAYS = 'codebuild.log_retention_days'  # CloudWatch retention for build logs


# dmichaels/2022-06-06: Factored out from base.py.
COMMON_STACK_PREFIX = "c4-"
COMMON_STACK_PREFIX_CAMEL_CASE = "C4"


class C4AppConfigBase:
    """ Factored out similar to Datastore for GAC name resolution """
    STACK_NAME_TOKEN = 'appconfig'
    STACK_TITLE_TOKEN = 'AppConfig'


# dmichaels/2022-06-06: Factored out from datastore.py.
class C4DatastoreBase:
    """
    Factored out of C4Datastore to generate names before orchestration (e.g. init-custom-dir).
    """
    STACK_NAME_TOKEN = "datastore"
    STACK_TITLE_TOKEN = "Datastore"
    APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX = 'ApplicationConfiguration'
    RDS_SECRET_NAME_SUFFIX = 'RDSSecret'  # Used as logical id suffix in resource names

    DEFAULT_RDS_DB_NAME = 'ebdb'
    DEFAULT_RDS_DB_PORT = '5432'
    DEFAULT_RDS_DB_USERNAME = 'postgresql'
    DEFAULT_RDS_AZ = 'us-east-1a'
    DEFAULT_RDS_STORAGE_SIZE = 30
    DEFAULT_RDS_INSTANCE_SIZE = 'db.t4g.medium'
    DEFAULT_RDS_STORAGE_TYPE = 'gp3'
    DEFAULT_RDS_POSTGRES_VERSION = '17.6'
    DEFAULT_RDS_BACKUP_RETENTION = 7  # days


class C4SRCEDatastoreBase(C4DatastoreBase):
    """
    SRCE variant of C4DatastoreBase. Used to generate SRCE datastore names before orchestration
    (e.g. setup-remaining-secrets). Inherits RDS defaults from C4DatastoreBase.
    """
    STACK_NAME_TOKEN = 'srce-datastore'
    STACK_TITLE_TOKEN = 'SRCEDatastore'


# dmichaels/2022-06-22: Factored out from C4IAM in iam.py.
class C4IAMBase:
    """
    Factored out of C4IAM to generate names before orchestration (e.g. the setup-remaining-secrets command).
    """
    STACK_NAME_TOKEN = "iam"
    STACK_TITLE_TOKEN = "IAM"
    SHARING = 'ecosystem'


# dmichaels/2022-07-05: Factored out from sentieon.py.
class C4SentieonSupportBase:
    STACK_NAME_TOKEN = 'sentieon'
    STACK_TITLE_TOKEN = 'Sentieon'


# dmichaels/2022-07-06: Factored out from network.py.
class C4NetworkBase:
    STACK_NAME_TOKEN = 'network'
    STACK_TITLE_TOKEN = 'Network'


class EC2Constants:
    DEFAULT_AMI_IMAGE = "ami-087c17d1fe0178315"
