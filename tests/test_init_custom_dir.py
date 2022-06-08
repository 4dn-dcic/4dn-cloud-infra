# IN PROGRESS: dmichaels/2022-06-08

import io
import json
import mock
import os
import re
import tempfile
import unittest

from contextlib import contextmanager

# TODO
# What is proper way to import these ... surely not like this?

from src.auto.init_custom_dir.cli import main


class TestInitCustomDir(unittest.TestCase):

    @contextmanager
    def setup_filesystem(self, env_name: str, custom_dir: str = "custom", account_number: str = None):
        """
        Sets up our directories to use in a system temporary directory, which gets
        totally cleaned up after the with-context which this returns is finished.
        Returns a tuple with the full path names of:
        - The created base temporary directory (just FYI).
        - The created AWS base directory (e.g. representing /my-home/.aws_test)
        - The created AWS environment directory (e.g. representing /my-home/.aws_test.my-test)
        - The not-created custom directory (e.g. representing /my-repos/4dn-cloud-infra/custom)
        If account_number is specified then also creates:
        - A test_creds.sh with an export for ACCOUNT_NUMBER will be created,
          e.g. representing /my-home/.aws_test.my-test/test_creds.sh
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            aws_dir = os.path.join(tmp_dir, ".aws_test")
            env_dir = os.path.join(tmp_dir, ".aws_test." + env_name)
            if not custom_dir:
                custom_dir = "custom"
            custom_dir = os.path.join(tmp_dir, custom_dir)
            test_creds_script_file = os.path.join(env_dir, "test_creds.sh")
            # aws_dir represents: /my-home/.aws_test
            os.makedirs(aws_dir)
            # env_dir represents: /my-home/.aws_test.my-test
            os.makedirs(env_dir)
            if account_number:
                with io.open(test_creds_script_file, "w") as test_creds_script_f:
                    # test_creds_script_file represents: /my-home/.aws_test.my-test/test_creds.sh
                    test_creds_script_f.write(f"export ACCOUNT_NUMBER={account_number}\n")
            yield tmp_dir, aws_dir, env_dir, custom_dir

    def call_main(self, pre_existing_custom_directory: bool = False, pre_existing_s3_encrypt_file: bool = True):

        my_env_name = "my-test"
        my_account_number = "1234567890"
        my_custom_dir = "custom"
        my_s3_bucket_org = "kmp"
        my_auth0_client = "0A39E193F7B74218A3F176872197D895"
        my_auth0_secret = "126EBFCAC9C74CD5B2CBAD7B3DCB3314"
        my_captcha_key = "5449963A45A4E9DAEDA36062405DDBE"
        my_captcha_secret = "08DEBE6BE73D49549B18CE9641D80DC5"
        my_deploying_iam_user = "someuser"
        my_s3_encrypt_key = "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if pre_existing_s3_encrypt_file else None

        with self.setup_filesystem(my_env_name, my_custom_dir, my_account_number)\
                as (tmp_dir, aws_dir, env_dir, custom_dir), \
             mock.patch('src.auto.init_custom_dir.cli.os.getlogin') as mock_os_getlogin, \
             mock.patch('builtins.print'), \
             mock.patch('src.auto.init_custom_dir.cli.PRINT'), \
             mock.patch('src.auto.init_custom_dir.utils.PRINT') as mock_utils_print, \
             mock.patch("builtins.input") as mock_input:

            mock_os_getlogin.return_value = my_deploying_iam_user
            mock_input.return_value = "yes"

            # This is the directory structure we are simulating;
            # well, actually creating, within a temporary directory.
            # Variable names used for each (below) in parenthesis.
            #
            #   /your-repos/4dn-cloud-infra/custom (custom_dir)
            #     ├── aws_creds@ -> /your-home/.aws_test.my-test (custom_aws_cred_dir, env_dir)
            #     │   ├── s3_encrypt_key.txt (s3_encrypt_key_file)
            #     │   └── test_creds.sh
            #     ├── config.json (config_json_file)
            #     └── secrets.json (secrets_json_file)

            custom_aws_creds_dir = os.path.join(custom_dir, "aws_creds")
            config_json_file = os.path.join(custom_dir, "config.json")
            secrets_json_file = os.path.join(custom_dir, "secrets.json")
            s3_encrypt_key_file = os.path.join(env_dir, "s3_encrypt_key.txt")

            if pre_existing_custom_directory:
                os.makedirs(custom_dir)
                pass

            if pre_existing_s3_encrypt_file:
                with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_f:
                    s3_encrypt_key_f.write(my_s3_encrypt_key)

            # Call the script function.

            argv = ["--env", my_env_name, "--awsdir", aws_dir, "--out", custom_dir,
                    "--s3org", my_s3_bucket_org,
                    "--auth0client", my_auth0_client, "--auth0secret", my_auth0_secret,
                    "--captchakey", my_captcha_key, "--captchasecret", my_captcha_secret]

            if pre_existing_custom_directory:
                with mock.patch('builtins.exit') as mock_exit:
                    #
                    # Wasn't quite sure how to do this.
                    # Patching exit will cause the main script to not actually exit;
                    # we'd like it just to return to this test on exit so raising exception.
                    #
                    mock_exit.side_effect = Exception()
                    with self.assertRaises(Exception):
                        main(argv)
                    assert mock_exit.called is True
                    assert mock_exit.call_count == 1
                    #
                    # Kinda lame.
                    #
                    last_print_arg = mock_utils_print.call_args.args[0]
                    assert re.search(".*exit.*without.*doing*", last_print_arg, re.IGNORECASE)
                    return
            else:
                main(argv)

            # Verify existence/contents of config.json file (e.g. in /my-repos/4dn-cloud-infra/custom/config.json).

            assert os.path.isfile(config_json_file)
            with io.open(config_json_file) as config_json_f:
                config_json = json.load(config_json_f)
                assert config_json["account_number"] == my_account_number
                assert config_json["s3.bucket.org"] == my_s3_bucket_org
                assert config_json["deploying_iam_user"] == my_deploying_iam_user
                assert config_json["identity"] == "C4DatastoreMyTestApplicationConfiguration"
                assert config_json["ENCODED_ENV_NAME"] == my_env_name

            # Verify existence/contents of secrets.json file (e.g. in /my-repos/4dn-cloud-infra/custom/secrets.json).

            assert os.path.isfile(secrets_json_file)
            with io.open(secrets_json_file) as secrets_json_f:
                secrets_json = json.load(secrets_json_f)
                assert secrets_json["Auth0Client"] == my_auth0_client
                assert secrets_json["Auth0Secret"] == my_auth0_secret
                assert secrets_json["reCaptchaKey"] == my_captcha_key
                assert secrets_json["reCaptchaSecret"] == my_captcha_secret

            # Verify that we have custom/aws_creds directory (e.g. in /my-repos/4dn-cloud-infra/custom/config.json).
            # And that it is actually a symlink to the AWS environment directory (e.g. to /my-home/.aws_test.my-test).

            assert os.path.isdir(custom_aws_creds_dir)
            assert os.path.islink(custom_aws_creds_dir)
            assert os.readlink(custom_aws_creds_dir) == env_dir

            # Verify that we have an s3_encrypt_key.txt file.
            # If we were called with pre_existing_s3_encrypt_file then the s3_encrypt_key.txt
            # file we created above (before calling the main script function) should have the same contents.
            # Otherwise, just check that it has some reasonable content.

            assert os.path.isfile(s3_encrypt_key_file)
            with io.open(s3_encrypt_key_file) as s3_encrypt_key_f:
                s3_encrypt_key = s3_encrypt_key_f.read()
                if pre_existing_s3_encrypt_file:
                    assert s3_encrypt_key == my_s3_encrypt_key
                else:
                    assert 32 <= len(s3_encrypt_key) <= 128

    def test_main(self):
        self.call_main(pre_existing_custom_directory=False, pre_existing_s3_encrypt_file=False)
        self.call_main(pre_existing_custom_directory=False, pre_existing_s3_encrypt_file=True)
        self.call_main(pre_existing_custom_directory=True)
