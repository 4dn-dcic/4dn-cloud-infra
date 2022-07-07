import io
import mock
import os
import tempfile
from typing import Optional
from contextlib import contextmanager
from dcicutils.qa_utils import (MockBoto3)
from src.auto.utils import aws_context
from src.auto.utils import aws


class TestData:
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
        aws_credentials_dir = os.path.join(tmpdir, TestData.aws_credentials_dir)
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


def _setup_aws_environ_that_should_be_ignored():
    aws_environ_vars = ["AWS_ACCESS_KEY_ID",
                        "AWS_SECRET_ACCESS_KEY",
                        "AWS_SHARED_CREDENTIALS_FILE",
                        "AWS_CONFIG_FILE",
                        "AWS_REGION",
                        "AWS_DEFAULT_REGION"]
    for aws_environ_var in aws_environ_vars:
        os.environ[aws_environ_var] = "UNUSED_" + aws_environ_var


def _test_aws_context(aws_credentials_dir: Optional[str],
                      aws_access_key_id: Optional[str],
                      aws_secret_access_key: Optional[str],
                      aws_region: Optional[str],
                      aws_environ_set: bool) -> None:

    mocked_boto = MockBoto3()
    mocked_boto.client("sts").put_caller_identity_for_testing(TestData.aws_account_number, TestData.aws_user_arn)

    if aws_environ_set:
        # Set AWS credentials environment variables that should NOT be found/used
        # because we're using AwsContext.establish_credentials which ignores environment.
        _setup_aws_environ_that_should_be_ignored()

    aws_object = aws.Aws(aws_credentials_dir, aws_access_key_id, aws_secret_access_key, aws_region)
    with mock.patch.object(aws_context, "boto3", mocked_boto):
        _setup_aws_environ_that_should_be_ignored()
        with aws_object.establish_credentials(display=True, show=True) as aws_credentials:
            assert aws_credentials.access_key_id == TestData.aws_access_key_id
            assert aws_credentials.secret_access_key == TestData.aws_secret_access_key
            assert aws_credentials.region == TestData.aws_region
            assert aws_credentials.account_number == TestData.aws_account_number
            assert aws_credentials.user_arn == TestData.aws_user_arn


def test_aws_context_with_credentials() -> None:
    _test_aws_context(None, TestData.aws_access_key_id, TestData.aws_secret_access_key, TestData.aws_region, False)
    _test_aws_context(None, TestData.aws_access_key_id, TestData.aws_secret_access_key, TestData.aws_region, True)


def test_aws_context_with_credentials_dir() -> None:
    with _setup_aws_credentials_dir(TestData.aws_access_key_id,
                                    TestData.aws_secret_access_key, TestData.aws_region) as aws_credentials_dir:
        _test_aws_context(aws_credentials_dir, None, None, None, False)
        _test_aws_context(aws_credentials_dir, None, None, None, True)
