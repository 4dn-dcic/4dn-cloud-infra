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


# Auxiliary secrets populated post-deploy: the CrowdStrike Falcon credentials owned by the
# per-env appconfig stack (created only when crowdstrike.enabled is set).


# Keys to look for in custom/secrets.json when sourcing aux credentials for upload.
class LocalSecretsKey:
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
