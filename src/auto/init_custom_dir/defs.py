# Definitions for files/paths, template variables, and evironment variables.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - os.path.abspath
#     - os.path.dirname
#     - os.path.join

import os


class InfraDirectories:
    AWS_DIR = "~/.aws_test"
    CUSTOM_DIR = "custom"
    CUSTOM_AWS_CREDS_DIR = "aws_creds"
    THIS_SCRIPT_DIR = os.path.dirname(__file__)

    @staticmethod
    def get_custom_aws_creds_dir(custom_dir: str) -> str:
        return os.path.abspath(os.path.join(custom_dir, InfraDirectories.CUSTOM_AWS_CREDS_DIR))


class InfraFiles:
    TEST_CREDS_SCRIPT_FILE = "test_creds.sh"
    CONFIG_FILE = "config.json"
    SECRETS_FILE = "secrets.json"
    CONFIG_TEMPLATE_FILE = "templates/config.template.json"
    SECRETS_TEMPLATE_FILE = "templates/secrets.template.json"
    S3_ENCRYPT_KEY_FILE = "s3_encrypt_key.txt"
    SYSTEM_WORDS_DICTIONARY_FILE = "/usr/share/dict/words"

    @staticmethod
    def get_test_creds_script_file(env_dir: str) -> str:
        return os.path.abspath(os.path.join(env_dir, InfraFiles.TEST_CREDS_SCRIPT_FILE))

    @staticmethod
    def get_config_file(custom_dir: str) -> str:
        return os.path.abspath(os.path.join(custom_dir, InfraFiles.CONFIG_FILE))

    @staticmethod
    def get_secrets_file(custom_dir: str) -> str:
        return os.path.abspath(os.path.join(custom_dir, InfraFiles.SECRETS_FILE))

    @staticmethod
    def get_config_template_file() -> str:
        return os.path.abspath(os.path.join(InfraDirectories.THIS_SCRIPT_DIR, InfraFiles.CONFIG_TEMPLATE_FILE))

    @staticmethod
    def get_secrets_template_file() -> str:
        return os.path.abspath(os.path.join(InfraDirectories.THIS_SCRIPT_DIR, InfraFiles.SECRETS_TEMPLATE_FILE))

    @staticmethod
    def get_s3_encrypt_key_file(custom_dir: str) -> str:
        return os.path.abspath(
            os.path.join(InfraDirectories.get_custom_aws_creds_dir(custom_dir), InfraFiles.S3_ENCRYPT_KEY_FILE))


class ConfigTemplateVars:
    ACCOUNT_NUMBER = "__TEMPLATE_ACCOUNT_NUMBER__"
    DEPLOYING_IAM_USER = "__TEMPLATE_DEPLOYING_IAM_USER__"
    IDENTITY = "__TEMPLATE_IDENTITY__"
    ENCODED_ENV_NAME = "__TEMPLATE_ENCODED_ENV_NAME__"
    S3_BUCKET_ORG = "__TEMPLATE_VALUE_S3_BUCKET_ORG__"


class SecretsTemplateVars:
    AUTH0_CLIENT = "__TEMPLATE_VALUE_AUTH0_CLIENT__"
    AUTH0_SECRET = "__TEMPLATE_VALUE_AUTH0_SECRET__"
    RE_CAPTCHA_KEY = "__TEMPLATE_VALUE_RE_CAPTCHA_KEY__"
    RE_CAPTCHA_SECRET = "__TEMPLATE_VALUE_RE_CAPTCHA_SECRET__"


class EnvVars:

    # This is used only to get this environment variable from the test_creds.sh file,
    # as a default/fallback in case it is not specified on command-line.

    ACCOUNT_NUMBER = "ACCOUNT_NUMBER"
