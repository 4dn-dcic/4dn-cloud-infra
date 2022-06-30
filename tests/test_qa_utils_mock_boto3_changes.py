# TODO: Move this into dcicutils/test/test_qa_utils.py. Here for now for easier testing.

from dcicutils.qa_utils import (MockBoto3, MockBoto3Iam, MockBoto3Kms, MockBoto3OpenSearch, MockBoto3Session)
import io
import os
import tempfile
import uuid


def test_mock_boto3_session():
    mock_boto3 = MockBoto3()
    assert isinstance(mock_boto3.client('session'), MockBoto3Session)
    assert isinstance(mock_boto3.client('session', region_name='us-east-1'), MockBoto3Session)


def test_mock_boto3_session_get_credentials_via_explicit():
    mock_boto3 = MockBoto3()
    mocked_session = mock_boto3.client('session')
#   mocked_session = mock_boto3.session.Session()

    # Test MockBoto3Session.get_credentials with explicitly-specified info.
    aws_access_key_id = str(uuid.uuid4())
    aws_secret_access_key = str(uuid.uuid4())
    aws_region = str(uuid.uuid4())
    mocked_session.unset_environ_credentials_for_testing()
    os.environ["AWS_ACCESS_KEY_ID"] = "do-not-find-this-access-key-id"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "do-not-find-this-secret-access-key"
    mocked_session.put_credentials_for_testing(aws_access_key_id=aws_access_key_id,
                                               aws_secret_access_key=aws_secret_access_key,
                                               region_name=aws_region,
                                               aws_credentials_dir=None)
    aws_credentials = mocked_session.get_credentials()
    assert aws_credentials.access_key == aws_access_key_id
    assert aws_credentials.secret_key == aws_secret_access_key
    assert mocked_session.region_name == aws_region


def test_mock_boto3_session_get_credentials_via_environment():
    mock_boto3 = MockBoto3()
    mocked_session = mock_boto3.client('session')

    # Test MockBoto3Session.get_credentials with environment-specified info.
    aws_access_key_id = str(uuid.uuid4())
    aws_secret_access_key = str(uuid.uuid4())
    aws_region = str(uuid.uuid4())
    mocked_session.unset_environ_credentials_for_testing()
    os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key_id
    os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_access_key
    mocked_session.put_credentials_for_testing(aws_access_key_id=None,
                                               aws_secret_access_key=None,
                                               region_name=aws_region,
                                               aws_credentials_dir=None)
    aws_credentials = mocked_session.get_credentials()
    assert aws_credentials.access_key == aws_access_key_id
    assert aws_credentials.secret_key == aws_secret_access_key
    assert mocked_session.region_name == aws_region


def test_mock_boto3_session_get_credentials_via_file():
    mock_boto3 = MockBoto3()
    mocked_session = mock_boto3.client('session')

    # Test MockBoto3Session.get_credentials with file-specified info.
    aws_access_key_id = str(uuid.uuid4())
    aws_secret_access_key = str(uuid.uuid4())
    aws_region = str(uuid.uuid4())
    with tempfile.TemporaryDirectory() as aws_credentials_dir:

        # Use file-specified info where credentials directory specified explicitly
        aws_credentials_file = os.path.join(aws_credentials_dir, "credentials")
        with io.open(aws_credentials_file, "w") as aws_credentials_fp:
            aws_credentials_fp.write(f"[default]\n")
            aws_credentials_fp.write(f"aws_access_key_id={aws_access_key_id}\n")
            aws_credentials_fp.write(f"aws_secret_access_key={aws_secret_access_key}\n")

        aws_config_file = os.path.join(aws_credentials_dir, "config")
        with io.open(aws_config_file, "w") as aws_config_fp:
            aws_config_fp.write(f"[default]\n")
            aws_config_fp.write(f"region={aws_region}\n")
        mocked_session.unset_environ_credentials_for_testing()
        mocked_session.put_credentials_for_testing(aws_access_key_id=None,
                                                   aws_secret_access_key=None,
                                                   region_name=None,
                                                   aws_credentials_dir=aws_credentials_dir)
        aws_credentials = mocked_session.get_credentials()
        assert aws_credentials.access_key == aws_access_key_id
        assert aws_credentials.secret_key == aws_secret_access_key
        assert mocked_session.region_name == aws_region

        # Use file-specified info where credentials/config files specified in environment variables.
        aws_region = str(uuid.uuid4())
        mocked_session.unset_environ_credentials_for_testing()
        os.environ["AWS_SHARED_CREDENTIALS_FILE"] = aws_credentials_file
        os.environ["AWS_CONFIG_FILE"] = aws_config_file
        os.environ["AWS_DEFAULT_REGION"] = aws_region
        mocked_session.put_credentials_for_testing(aws_access_key_id=None,
                                                   aws_secret_access_key=None,
                                                   region_name=None,
                                                   aws_credentials_dir=None)
        aws_credentials = mocked_session.get_credentials()
        assert aws_credentials.access_key == aws_access_key_id
        assert aws_credentials.secret_key == aws_secret_access_key
        assert mocked_session.region_name == aws_region


def test_mock_boto3_iam():
    mock_boto3 = MockBoto3()
    assert isinstance(mock_boto3.client('iam'), MockBoto3Iam)


def test_mock_boto3_kms():
    mock_boto3 = MockBoto3()
    assert isinstance(mock_boto3.client('kms'), MockBoto3Kms)


def test_mock_boto3_opensearch():
    mock_boto3 = MockBoto3()
    assert isinstance(mock_boto3.client('opensearch'), MockBoto3OpenSearch)
