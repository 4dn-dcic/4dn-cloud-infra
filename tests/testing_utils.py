from contextlib import contextmanager
import io
import json
import os
import re
import tempfile
from typing import Callable, Optional


@contextmanager
def setup_aws_credentials_dir(aws_access_key_id: str, aws_secret_access_key: str, aws_region: str = None):
    """
    Sets up an AWS credentials directory, in a system temporary directory (for the lifetime
    of this context manager), containing a credentials file with the given AWS access key
    ID and secret access key, and optionally a config file containing the given AWS region.

    :param aws_access_key_id: AWS access key ID
    :param aws_secret_access_key: AWS secret access key
    :param aws_secret_access_key: AWS region name
    :return: Yields full path to the temporary credentials directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        aws_credentials_dir = os.path.join(tmpdir, "custom/aws_creds")
        os.makedirs(aws_credentials_dir)
        aws_credentials_file = os.path.join(aws_credentials_dir, "credentials")
        with io.open(aws_credentials_file, "w") as aws_credentials_fp:
            aws_credentials_fp.write(f"[default]\n")
            aws_credentials_fp.write(f"aws_access_key_id={aws_access_key_id}\n")
            aws_credentials_fp.write(f"aws_secret_access_key={aws_secret_access_key}\n")
        if aws_region:
            aws_config_file = os.path.join(aws_credentials_dir, "config")
            with io.open(aws_config_file, "w") as aws_config_fp:
                aws_config_fp.write(f"[default]\n")
                aws_config_fp.write(f"region={aws_region}\n")
        yield aws_credentials_dir


@contextmanager
def setup_custom_dir(aws_credentials_name: str, aws_account_number: str, encryption_enabled: bool = False):
    """
    Sets up a custom config directory, in a system temporary directory (for the lifetime of this context manager),
    containing a config.json file with the given AWS credentials name (e.g. cgap-supertest), and AWS account number.

    :param aws_credentials_name: AWS credentials name (e.g. cgap-superttest).
    :param aws_account_number: AWS account number (e.g. 466564410312)
    :return: Yields full path to the temporary custom directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, "custom")
        os.makedirs(custom_dir)
        config_file = os.path.join(custom_dir, "config.json")
        with io.open(config_file, "w") as config_file_fp:
            config_json = {}
            config_json["account_number"] = aws_account_number
            config_json["ENCODED_ENV_NAME"] = aws_credentials_name
            if encryption_enabled:
                config_json["s3.bucket.encryption"] = True
            config_file_fp.write(json.dumps(config_json))
        yield custom_dir


def rummage_for_print_message(mocked_print, regular_expression: str) -> Optional[str]:
    """
    Searches the given print mock for the/a print call whose argument matches the given regular
    expression, and returns that argument for the first one that matches; if not found returns None.

    :param mocked_print: Mock print object.
    :param regular_expression: Regular expression to look for in mock print values/lines.
    :return: First message matching the given regular expression or None if not found.
    """
    for line in mocked_print.lines:
        if re.search(regular_expression, line, re.IGNORECASE):
            return line
    return None


def rummage_for_print_message_all(mocked_print, regular_expression: str, predicate: Callable) -> bool:
    """
    Searches the given print mock for the/a call whose argument matches the given regular
    expression and returns True iff EVERY match ALSO passes (gets a True return value
    from) the given predicate function with that argument, otherwise returns False.

    :param mocked_print: Mock print object.
    :param regular_expression: Regular expression to look for in mock print output values/lines.
    :param predicate: Regular expression to look for in mock print values/lines.
    :return: True if ALL matched mock print values/lines passes the given predicate test otherwise False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            if not predicate(value):
                return False
    return True
