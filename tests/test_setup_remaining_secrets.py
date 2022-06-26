import boto3
import io
import json
import mock
import os
import pytest
import re
import stat
import sys
import tempfile
from typing import Callable
from contextlib import contextmanager
from dcicutils.qa_utils import (printed_output as mock_print, MockBoto3, MockBoto3SecretsManager, MockBoto3Session, MockBoto3Sts)
from src.auto.setup_remaining_secrets.cli import main
from src.auto.utils.locations import InfraDirectories, InfraFiles
from src.auto.utils import aws_context
from src.auto.utils import aws

class Input:
    aws_access_key_id = "B21897CC-193E-4E29-B1F6-3384B55223C5"
    aws_account_number = "F18355BA-D449-4750-AAE2-136A02368639"
    aws_credentials_dir = "custom/aws_creds"
    aws_credentials_name = "cgap-unit-test"
    aws_region = "us-west-2"
    aws_secret_access_key = "0FF64D59-615B-4DEA-8F7F-9EEE50F4246A"
    aws_user_arn = "1B1CCA38-1CC8-4979-9213-85C6B664C0AA"

@contextmanager
def _setup_aws_credentials_dir(aws_access_key_id: str, aws_secret_access_key: str, aws_region: str = None):
    with tempfile.TemporaryDirectory() as tmpdir:
        aws_credentials_dir = os.path.join(tmpdir, Input.aws_credentials_dir)
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
        yield aws_credentials_file

def test_setup_remaining_secrets() -> None:
    # Not yet implemented.
    pass

def test_aws_context_with_explicit_credentials() -> None:

    mocked_boto = MockBoto3()
    mocked_boto.client('session').unset_environ_credentials_for_testing()
    mocked_boto.client('sts').set_caller_identity_for_testing({
        "Account": Input.aws_account_number,
        "Arn": Input.aws_user_arn
    })
    aws_object = aws.Aws(None, Input.aws_access_key_id, Input.aws_secret_access_key, Input.aws_region)
    with mock.patch.object(aws_context, "boto3", mocked_boto):
        with aws_object.establish_credentials(display=True, show=True) as aws_credentials:
            assert aws_credentials.access_key_id == Input.aws_access_key_id
            assert aws_credentials.secret_access_key == Input.aws_secret_access_key
            assert aws_credentials.default_region == Input.aws_region

def test_aws_context_with_explicit_credentials_dir() -> None:
    mocked_boto = MockBoto3()
    mocked_boto.client('sts').set_caller_identity_for_testing({
        "Account": Input.aws_account_number,
        "Arn": Input.aws_user_arn
    })
    with _setup_aws_credentials_dir(Input.aws_access_key_id, Input.aws_secret_access_key, Input.aws_region) as aws_credentials_file:
        aws_object = aws.Aws(os.path.dirname(aws_credentials_file))
        with mock.patch.object(aws_context, "boto3", mocked_boto):
            with aws_object.establish_credentials(display=True, show=True) as aws_credentials:
                assert aws_credentials.access_key_id == Input.aws_access_key_id
        pass
