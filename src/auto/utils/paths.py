# Definitions for files/paths used in 4dn-cloud-infra setup automation.

import os


class InfraDirectories:
    AWS_DIR = "~/.aws_test"
    CUSTOM_DIR = "custom"
    CUSTOM_AWS_CREDS_DIR = "aws_creds"
    THIS_SCRIPT_DIR = os.path.dirname(__file__)

    @staticmethod
    def get_custom_dir(custom_dir: str = None) -> str:
        # Note this returns the given directory relative to the CURRENT directory.
        if not custom_dir:
            custom_dir = InfraDirectories.CUSTOM_DIR
        return os.path.abspath(os.path.expanduser(custom_dir))

    @staticmethod
    def get_custom_aws_creds_dir(custom_dir: str = None) -> str:
        if not custom_dir:
            custom_dir = InfraDirectories.get_custom_dir()
        return os.path.abspath(os.path.join(custom_dir, InfraDirectories.CUSTOM_AWS_CREDS_DIR))


class InfraFiles:
    TEST_CREDS_SCRIPT_FILE = "test_creds.sh"
    CONFIG_FILE = "config.json"
    SECRETS_FILE = "secrets.json"
    CONFIG_TEMPLATE_FILE = "../templates/config.template.json"
    SECRETS_TEMPLATE_FILE = "../templates/secrets.template.json"
    S3_ENCRYPT_KEY_FILE = "s3_encrypt_key.txt"

    @staticmethod
    def get_test_creds_script_file(aws_credentials_dir: str) -> str:
        return os.path.abspath(os.path.join(aws_credentials_dir, InfraFiles.TEST_CREDS_SCRIPT_FILE))

    @staticmethod
    def get_config_file(custom_dir: str = None) -> str:
        if not custom_dir:
            custom_dir = InfraDirectories.get_custom_dir()
        return os.path.abspath(os.path.join(custom_dir, InfraFiles.CONFIG_FILE))

    @staticmethod
    def get_secrets_file(custom_dir: str = None) -> str:
        if not custom_dir:
            custom_dir = InfraDirectories.get_custom_dir()
        return os.path.abspath(os.path.join(custom_dir, InfraFiles.SECRETS_FILE))

    @staticmethod
    def get_config_template_file() -> str:
        return os.path.abspath(os.path.join(InfraDirectories.THIS_SCRIPT_DIR, InfraFiles.CONFIG_TEMPLATE_FILE))

    @staticmethod
    def get_secrets_template_file() -> str:
        return os.path.abspath(os.path.join(InfraDirectories.THIS_SCRIPT_DIR, InfraFiles.SECRETS_TEMPLATE_FILE))

    @staticmethod
    def get_s3_encrypt_key_file(custom_dir: str) -> str:
        if not custom_dir:
            custom_dir = InfraDirectories.get_custom_dir()
        return os.path.abspath(
            os.path.join(InfraDirectories.get_custom_aws_creds_dir(custom_dir), InfraFiles.S3_ENCRYPT_KEY_FILE))


class MiscFiles:
    DICTIONARY_WORDS_FILE = "/usr/share/dict/words"
    ALTERNATE_DICTIONARY_WORDS_FILE = "/usr/dict/words"
