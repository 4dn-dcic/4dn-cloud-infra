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


# Auxiliary secrets populated post-deploy. DockerHub credentials are owned by the
# ecosystem-scoped shared-secrets stack (C4SharedSecrets); the Falcon secrets are owned by the
# per-env appconfig stack.
class DockerHubSecretKeyName:
    """Keys inside the DockerHub credentials JSON secret (owned by C4SharedSecrets)."""
    USERNAME = "username"
    TOKEN = "token"


# Keys to look for in custom/secrets.json when sourcing aux credentials for upload.
class LocalSecretsKey:
    DOCKERHUB_USERNAME = "DockerHubUsername"
    DOCKERHUB_TOKEN = "DockerHubToken"
    FALCON_CID = "FalconCID"
    FALCON_CLIENT_ID = "FalconClientID"
    FALCON_CLIENT_SECRET = "FalconClientSecret"


# Logical-id suffixes for the Falcon secrets owned by appconfig.C4AppConfig — repeated here so
# this script can compute the AWS secret names without importing the troposphere-heavy appconfig
# module. Falcon secrets are env-suffixed off the appconfig stack name.
class AuxSecretSuffix:
    FALCON_CID = "FalconCID"
    FALCON_CLIENT_ID = "FalconClientID"
    FALCON_CLIENT_SECRET = "FalconClientSecret"


# Fixed AWS Secrets Manager name for DockerHub credentials. Must match
# C4SharedSecrets.DOCKERHUB_SECRET_NAME in src/parts/shared_secrets.py.
DOCKERHUB_SECRET_NAME = "dhi-registry-credentials"
