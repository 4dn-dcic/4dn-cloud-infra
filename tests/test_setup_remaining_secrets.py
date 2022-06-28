import boto3
import io
import mock
import os
import sys
import tempfile
from typing import Callable
from src.auto.setup_remaining_secrets.cli import main
from contextlib import contextmanager
from dcicutils.qa_utils import (printed_output as mock_print, MockBoto3, MockBoto3SecretsManager, MockBoto3Session, MockBoto3Sts)
from src.auto.setup_remaining_secrets.defs import SecretKeyNames
from src.auto.utils import aws_context
from src.auto.utils import aws
from .utils.utils_for_testing import (rummage_for_print_message, rummage_for_print_message_all)


class Input:
    config_file = "config.json"
    custom_dir = "custom"

    gac_secret_name = "C4DatastoreCgapUnitTestApplicationConfiguration"
    rds_secret_name = "C4DatastoreCgapUnitTestRDSSecret"

    aws_credentials_name = "cgap-unit-test"
    aws_credentials_dir = os.path.join(custom_dir, "aws_creds")
    aws_access_key_id = "AWS-ACCESS-KEY-ID-FOR-TESTING"
    aws_secret_access_key = "AWS-SECRET-ACCESS-KEY-FOR-TESTING"
    aws_account_number = "1234567890"
    aws_region = "us-west-2"
    aws_user_arn = f"arn:aws:iam::{aws_account_number}:user/user.for.testing"
    aws_iam_users = ["ts.eliot", "j.alfred.prufrock", "c4-iam-main-stack-C4IAMMainApplicationS3Federator-ZFK91VU2DM1H"]
    aws_iam_roles = [f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
                     f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
                     f"arn:aws:iam::{aws_account_number}:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K"]

    elasticsearch_name = f"es-{aws_credentials_name}"
    elasticsearch_host = "elasticsearch.server.for.testing"
    elasticsearch_port = 443
    elasticsearch_https = elasticsearch_port == 443
    elasticsearch_server = f"{elasticsearch_host}:{elasticsearch_port}"
    rds_host = "rds.host.for.testing"
    rds_password = "rds-password-for-testing"


@contextmanager
def _setup_aws_credentials_dir(aws_access_key_id: str, aws_secret_access_key: str, aws_region: str = None):
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
        yield aws_credentials_dir


@contextmanager
def _setup_custom_dir(aws_credentials_name: str, aws_account_number: str):
    """
    Sets up a custom config directory, in a system temporary directory (for the lifetime of this context manager),
    containing a config.json file with the given AWS credentials name (e.g. cgap-supertest), and AWS account number.

    :param aws_credentials_name: AWS credentials name (e.g. cgap-superttest).
    :param aws_account_number: AWS account number (e.g. 466564410312)
    :return: Yields full path to the temporary custom directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_dir = os.path.join(tmpdir, Input.custom_dir)
        os.makedirs(custom_dir)
        config_file = os.path.join(custom_dir, Input.config_file)
        with io.open(config_file, "w") as config_file_fp:
            config_file_fp.write(f'{{ "account_number": "{aws_account_number}", "ENCODED_ENV_NAME": "{aws_credentials_name}" }}\n')
        yield custom_dir


def _rummage_for_print_message(mocked_print, regular_expression: str) -> bool:
    """
    Searches the given print mock for the/a print call whose arguments matches the given regular
    expression, and returns True if it finds (at least) ONE that matches, otherwise returns False.

    :param mocked_print: Mock print object.
    :param regular_expression: Regular expression to look for in mock print values/lines.
    :return: True if at least one match found otherwise False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            return True
    return False


def _rummage_for_print_message_all(mocked_print, regular_expression: str, predicate: Callable) -> bool:
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


def test_setup_remaining_secrets() -> None:
    mocked_boto = MockBoto3()
    mocked_boto.client("iam").put_users_for_testing(Input.aws_iam_users)
    mocked_boto.client("iam").put_roles_for_testing(Input.aws_iam_roles)
    mocked_boto.client("opensearch").put_domain_for_testing(Input.elasticsearch_name, Input.elasticsearch_host, Input.elasticsearch_https)
    mocked_boto.client("sts").put_caller_identity_for_testing(Input.aws_account_number, Input.aws_user_arn)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.rds_secret_name, "host", Input.rds_host)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.rds_secret_name, "password", Input.rds_password)
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, "ACCOUNT_NUMBER", "some-existing-account-number")
    mocked_boto.client("secretsmanager").put_secret_key_value_for_testing(Input.gac_secret_name, "ENCODED_IDENTITY", "some-existing-encoded-identity")
    with _setup_aws_credentials_dir(Input.aws_access_key_id, Input.aws_secret_access_key, Input.aws_region) as aws_credentials_dir, \
         _setup_custom_dir(Input.aws_credentials_name, Input.aws_account_number) as custom_dir, \
         mock.patch.object(aws_context, "boto3", mocked_boto), \
         mock.patch.object(aws, "boto3", mocked_boto), \
         mock.patch("builtins.input") as mocked_input:
        mocked_input.return_value = "yes"
        main(["--aws-credentials-dir", aws_credentials_dir, "--custom-dir", custom_dir])
        assert Input.aws_account_number == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.ACCOUNT_NUMBER)
        assert Input.gac_secret_name == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.ENCODED_IDENTITY)
        assert Input.rds_host == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.RDS_HOST)
        assert Input.elasticsearch_server == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.ENCODED_ES_SERVER)
        assert Input.rds_password == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.RDS_PASSWORD)
        assert Input.rds_password == mocked_boto.client("secretsmanager").get_secret_key_value_for_testing(Input.gac_secret_name, SecretKeyNames.RDS_PASSWORD)


def xxx_test_setup_remaining_secrets() -> None:
    # Not yet implemented.
    mocked_boto = MockBoto3()
    mocked_boto.client("iam").put_users_for_testing(Input.aws_iam_users)
    mocked_boto.client("iam").put_roles_for_testing(Input.aws_iam_roles)
    mocked_boto.client("opensearch").put_domain_for_testing("es-server-domain-name", "es-server-domain-host", True)
    aws_object = aws.Aws(None, Input.aws_access_key_id, Input.aws_secret_access_key, Input.aws_region)
    #with mock.patch.object(aws_context, "boto3", mocked_boto):
    with mock.patch.object(sys.modules[__name__], "boto3", mocked_boto):
        iam = boto3.resource('iam')
        print("USERS")
        for user in iam.users.all():
            print(f"USER:[{user.name}]")
            pair = user.create_access_key_pair()
            access_key_pairs = iam.list_access_keys(UserName=user.name)
            access_key_pairs = access_key_pairs.get("AccessKeyMetadata")
            for access_key_pair in access_key_pairs:
                print(f"ACCESS KEY PAIR:[{access_key_pair.id},{access_key_pair.secret}]")
                print(f"ACCESS KEY PAIR2:[{access_key_pair['AccessKeyId']},{access_key_pair['CreateDate']}]")
        print("ROLES")
        for role in iam.list_roles()["Roles"]:
            print(f"ROLE:[{role['Arn']}]")
        sm = boto3.client('secretsmanager')
        sm.put_secret_value_for_testing('foo', 'bar')
        x = sm.get_secret_value('foo')
        print('secretdadsfasdfasdfasdfadsfasdfasdf')
        print(x)
        assert 1 == 1
        os = boto3.client("opensearch")
        domain_names = os.list_domain_names()
        print('foobar2')
        print(domain_names)
        print('foobar3')
        print(domain_names["DomainNames"][0])
        domain_name = domain_names["DomainNames"][0]["DomainName"]
        print(domain_names["DomainNames"][0]["DomainName"])
        print(domain_names["DomainNames"][0]["DomainStatus"])
        print(domain_names["DomainNames"][0]["DomainStatus"]["Endpoints"])
        print(domain_names["DomainNames"][0]["DomainStatus"]["Endpoints"]["vpc"])

        print(f"domain_name: {domain_name}")
        domain_description = os.describe_domain(domain_name)
        domain_status = domain_description["DomainStatus"]
        domain_endpoints = domain_status["Endpoints"]
        domain_endpoint_options = domain_status["DomainEndpointOptions"]
        domain_endpoint_vpc = domain_endpoints["vpc"]
        print(f"domain_endpoint_vpc: {domain_endpoint_vpc}")
        domain_endpoint_https = domain_endpoint_options["EnforceHTTPS"]
        if domain_endpoint_https:
            domain_endpoint = f"{domain_endpoint_vpc}:443"
        else:
            domain_endpoint = f"{domain_endpoint_vpc}:80"
        print(f"endpoint: {domain_endpoint}")

        #for domain_name in domain_names:
        #    print(domain_name)
