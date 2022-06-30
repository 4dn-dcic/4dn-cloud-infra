# Definitions for files/paths, template variables, and evironment variables.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - os.path.abspath
#     - os.path.dirname
#     - os.path.join

from ..utils.locations import (InfraDirectories, InfraFiles)  # noqa


class ConfigTemplateVars:
    ACCOUNT_NUMBER = "<account-number>"
    DEPLOYING_IAM_USER = "<deploying-iam-user>"
    IDENTITY = "<identity>"
    ENCODED_ENV_NAME = "<encoded-env-name>"
    S3_BUCKET_ORG = "<s3-bucket-org>"
    S3_BUCKET_ENCRYPTION = "<s3-bucket-encryption>"


class SecretsTemplateVars:
    AUTH0_CLIENT = "<auth0-client>"
    AUTH0_SECRET = "<auth0-secret>"
    RECAPTCHA_KEY = "<recaptcha-key>"
    RECAPTCHA_SECRET = "<recaptcha-secret>"


class EnvVars:

    # This is used only to get this environment variable from the test_creds.sh file,
    # as a default/fallback in case it is not specified on command-line.
    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
