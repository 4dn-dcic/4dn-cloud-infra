class GacSecretKeyName:
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
    ENCODED_IDENTITY = "ENCODED_IDENTITY"
    ENCODED_ES_SERVER = "ENCODED_ES_SERVER"
    ENCODED_S3_ENCRYPT_KEY_ID = "ENCODED_S3_ENCRYPT_KEY_ID"
    RDS_HOSTNAME = "RDS_HOSTNAME"
    RDS_PASSWORD = "RDS_PASSWORD"
    S3_AWS_ACCESS_KEY_ID = "S3_AWS_ACCESS_KEY_ID"
    S3_AWS_SECRET_ACCESS_KEY = "S3_AWS_SECRET_ACCESS_KEY"


class RdsSecretKeyName:
    RDS_HOSTNAME = "host"
    RDS_PASSWORD = "password"


# Auxiliary secrets owned by the appconfig stack and populated post-deploy alongside the GAC.
class DockerHubSecretKeyName:
    """Keys inside the appconfig-owned DockerHub credentials JSON secret."""
    USERNAME = "username"
    TOKEN = "token"


# Keys to look for in custom/secrets.json when sourcing aux credentials for upload.
class LocalSecretsKey:
    DOCKERHUB_USERNAME = "DockerHubUsername"
    DOCKERHUB_TOKEN = "DockerHubToken"
    FALCON_CID = "FalconCID"
    FALCON_CLIENT_ID = "FalconClientID"
    FALCON_CLIENT_SECRET = "FalconClientSecret"


# Logical-id suffixes used by appconfig.C4AppConfig — repeated here so this script can
# compute the AWS secret names without importing the troposphere-heavy appconfig module.
# Falcon secrets are env-suffixed off the appconfig stack name; DockerHub credentials
# use a fixed account-wide name (matches C4AppConfig.DOCKERHUB_SECRET_NAME).
class AuxSecretSuffix:
    FALCON_CID = "FalconCID"
    FALCON_CLIENT_ID = "FalconClientID"
    FALCON_CLIENT_SECRET = "FalconClientSecret"


# Fixed AWS Secrets Manager name for DockerHub credentials. Must match
# C4AppConfig.DOCKERHUB_SECRET_NAME in src/parts/appconfig.py.
DOCKERHUB_SECRET_NAME = "dhi-registry-credentials"
