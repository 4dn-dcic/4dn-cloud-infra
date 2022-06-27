import boto3
import io
import mock
import os
import sys
import tempfile
from contextlib import contextmanager
from dcicutils.qa_utils import (printed_output as mock_print, MockBoto3, MockBoto3SecretsManager, MockBoto3Session, MockBoto3Sts)
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
    aws_iam_users = ["ts.eliot", "j.alfred.prufrock", "herman.melville", "ishmael"]
    aws_iam_roles = ["arn:aws:iam::466564410312:role/c4-foursight-cgap-supertest-stac-MorningChecksRole-WGH127MP730T",
                     "arn:aws:iam::466564410312:role/c4-foursight-cgap-supertest-stack-ApiHandlerRole-KU4H3AHIJLJ6",
                     "arn:aws:iam::466564410312:role/c4-foursight-cgap-supertest-stack-CheckRunnerRole-15TKMDZVFQN2K"]


def test_setup_remaining_secrets() -> None:
    # Not yet implemented.
    mocked_boto = MockBoto3()
    mocked_boto.client("iam").put_users_for_testing(Input.aws_iam_users)
    mocked_boto.client("iam").put_roles_for_testing(Input.aws_iam_roles)
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
