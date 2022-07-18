from contextlib import contextmanager
import io
import json
import mock
import os
import re
import tempfile
from typing import Callable, Optional
from dcicutils import cloudformation_utils
from src.auto.utils import aws, aws_context


@contextmanager
def temporary_aws_credentials_dir_for_testing(aws_access_key_id: str,
                                              aws_secret_access_key: str,
                                              aws_region: str = None):
    """
    Sets up an AWS credentials directory, in a system temporary directory (for the lifetime
    of this context manager), containing a credentials file with the given AWS access key
    ID and secret access key, and optionally a config file containing the given AWS region.

    :param aws_access_key_id: AWS access key ID
    :param aws_secret_access_key: AWS secret access key
    :param aws_region: AWS region name
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
def temporary_custom_dir_for_testing(aws_credentials_name: str,
                                     aws_account_number: str,
                                     encryption_enabled: bool = False):
    """
    Sets up a custom config directory, in a system temporary directory (for the lifetime of this context manager),
    containing a config.json file with the given AWS credentials name (e.g. cgap-supertest), and AWS account number.

    :param aws_credentials_name: AWS credentials name (e.g. cgap-superttest).
    :param aws_account_number: AWS account number (e.g. 466564410312)
    :param encryption_enabled: True iff encryption should be enabled otherwise False.
    :return: Yields full path to the temporary custom directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, "custom")
        os.makedirs(custom_dir)
        config_file = os.path.join(custom_dir, "config.json")
        with io.open(config_file, "w") as config_file_fp:
            config_json = dict()
            config_json["account_number"] = aws_account_number
            config_json["ENCODED_ENV_NAME"] = aws_credentials_name
            if encryption_enabled:
                config_json["s3.bucket.encryption"] = True
            config_file_fp.write(json.dumps(config_json))
        yield custom_dir


@contextmanager
def temporary_custom_and_aws_credentials_dirs_for_testing(mocked_boto, test_data):
    mocked_boto.client("sts").put_caller_identity_for_testing(test_data.aws_account_number, test_data.aws_user_arn)
    with temporary_aws_credentials_dir_for_testing(
            test_data.aws_access_key_id,
            test_data.aws_secret_access_key,
            test_data.aws_region) as aws_credentials_dir, \
         temporary_custom_dir_for_testing(
            test_data.aws_credentials_name,
            test_data.aws_account_number, True) as custom_dir, \
         mock.patch.object(cloudformation_utils, "boto3", mocked_boto), \
         mock.patch.object(aws_context, "boto3", mocked_boto), \
         mock.patch.object(aws, "boto3", mocked_boto):
        yield custom_dir, aws_credentials_dir


def find_matching_line(lines: list, regular_expression: str, predicate: Optional[Callable] = None) -> Optional[str]:
    """
    Searches the given print mock for the/a print call whose argument matches the given regular
    expression, and returns that argument for the first one that matches; if not found returns None.

    :param lines: List/array of lines.
    :param regular_expression: Regular expression to look for in mock print values/lines.
    :param predicate: Optional function taking matched line and returning a True or False indicating match or not.
    :return: First message matching the given regular expression or None if not found.
    """
    predicate = predicate or (lambda _: True)
    for line in lines:
        if re.search(regular_expression, line, re.IGNORECASE):
            if predicate(line):
                return line
    return None


def all_lines_match(lines: list, regular_expression: str, predicate: Callable) -> bool:
    """
    Searches the given print mock for the/a call whose argument matches the given regular
    expression and returns True iff EVERY match ALSO passes (gets a True return value
    from) the given predicate function with that argument, otherwise returns False.

    :param lines: List/array of lines.
    :param regular_expression: Regular expression to look for in mock print output values/lines.
    :param predicate: Function taking matched line and returning a True or False indicating match or not.
    :return: True if ALL matched mock print values/lines passes the given predicate test otherwise False.
    """
    for value in lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            if not predicate(value):
                return False
    return True
