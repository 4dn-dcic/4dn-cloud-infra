import io
import json
import mock
import os
import re
import stat
import tempfile
import unittest
from contextlib import contextmanager
from src.auto.init_custom_dir.cli import main
from src.auto.init_custom_dir.defs import InfraDirectories, InfraFiles
from src.auto.init_custom_dir.utils import obfuscate


class TestMain(unittest.TestCase):
    """
    Tests for the main init-custom-dir script.
    """

    class Inputs:
        env_name = "my-test"
        account_number = "1234567890"
        s3_bucket_org = "prufrock"
        auth0_client = "0A39E193F7B74218A3F176872197D895"
        auth0_secret = "126EBFCAC9C74CD5B2CBAD7B3DCB3314"
        re_captcha_key = "5449963A45A4E9DAEDA36062405DDBE"
        re_captcha_secret = "08DEBE6BE73D49549B18CE9641D80DC5"
        deploying_iam_user = "someuser"
        s3_encrypt_key = "8F383EBE093941B5B927279F361C3002"
        dummy_json_content = "{\"dummy\": \"<dummy-content>\" }"

    def _get_standard_main_args(self, aws_dir: str, env_name: str, custom_dir: str) -> list:
        return ["--awsdir", aws_dir,
                "--env", env_name,
                "--out", custom_dir,
                "--s3org", self.Inputs.s3_bucket_org,
                "--auth0client", self.Inputs.auth0_client, "--auth0secret", self.Inputs.auth0_secret,
                "--recaptchakey", self.Inputs.re_captcha_key, "--recaptchasecret", self.Inputs.re_captcha_secret]

    @contextmanager
    def _setup_filesystem(self, env_name: str, account_number: str = None):
        """
        Sets up our directories to use in a system temporary directory,
        which gets totally cleaned up after the with-context where this is used.
        Returns (yields) a tuple with the full path names of:
        - The created AWS base directory (e.g. representing /my-home/.aws_test)
        - The created AWS environment directory (e.g. representing /my-home/.aws_test.my-test)
        - The NOT-created custom directory (e.g. representing /my-repos/4dn-cloud-infra/custom)
        If account_number is specified then also creates:
        - A test_creds.sh with an export for ACCOUNT_NUMBER will be created,
          e.g. representing /my-home/.aws_test.my-test/test_creds.sh
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            aws_dir = os.path.join(tmp_dir, ".aws_test")
            env_dir = os.path.join(tmp_dir, ".aws_test." + env_name)
            custom_dir = os.path.join(tmp_dir, "custom")
            test_creds_script_file = os.path.join(env_dir, "test_creds.sh")
            # aws_dir represents: /my-home/.aws_test
            os.makedirs(aws_dir)
            # env_dir represents: /my-home/.aws_test.my-test
            os.makedirs(env_dir)
            if account_number:
                with io.open(test_creds_script_file, "w") as test_creds_script_f:
                    # test_creds_script_file represents: /my-home/.aws_test.my-test/test_creds.sh
                    test_creds_script_f.write(f"export ACCOUNT_NUMBER={account_number}\n")
            yield aws_dir, env_dir, custom_dir

    def _call_main(self, pre_existing_s3_encrypt_key_file: bool = True):

        with self._setup_filesystem(self.Inputs.env_name, self.Inputs.account_number)\
                as (aws_dir, env_dir, custom_dir), \
             mock.patch("src.auto.init_custom_dir.cli.os.getlogin") as mock_os_getlogin, \
             mock.patch("src.auto.init_custom_dir.cli.PRINT") as mock_cli_print, \
             mock.patch("src.auto.init_custom_dir.utils.PRINT"), \
             mock.patch("builtins.input") as mock_input:

            mock_os_getlogin.return_value = self.Inputs.deploying_iam_user
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

            if pre_existing_s3_encrypt_key_file:
                with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_f:
                    s3_encrypt_key_f.write(self.Inputs.s3_encrypt_key)

            # Call the main script function.
            # Normal case where custom directory does not already exist.

            argv = self._get_standard_main_args(aws_dir, self.Inputs.env_name, custom_dir)
            main(argv)

            # Verify existence/contents of config.json file (e.g. in /my-repos/4dn-cloud-infra/custom/config.json).

            assert os.path.isfile(config_json_file)
            with io.open(config_json_file, "r") as config_json_f:
                config_json = json.load(config_json_f)
                assert config_json["account_number"] == self.Inputs.account_number
                assert config_json["s3.bucket.org"] == self.Inputs.s3_bucket_org
                assert config_json["deploying_iam_user"] == self.Inputs.deploying_iam_user
                assert config_json["identity"] == "C4DatastoreMyTestApplicationConfiguration"
                assert config_json["ENCODED_ENV_NAME"] == self.Inputs.env_name

            # Verify existence/contents of secrets.json file (e.g. in /my-repos/4dn-cloud-infra/custom/secrets.json).

            assert os.path.isfile(secrets_json_file)
            with io.open(secrets_json_file, "r") as secrets_json_f:
                secrets_json = json.load(secrets_json_f)
                assert secrets_json["Auth0Client"] == self.Inputs.auth0_client
                assert secrets_json["Auth0Secret"] == self.Inputs.auth0_secret
                assert secrets_json["reCaptchaKey"] == self.Inputs.re_captcha_key
                assert secrets_json["reCaptchaSecret"] == self.Inputs.re_captcha_secret

            # Verify that we have custom/aws_creds directory (e.g. in /my-repos/4dn-cloud-infra/custom/config.json).
            # And that it is actually a symlink to the AWS environment directory (e.g. to /my-home/.aws_test.my-test).

            assert os.path.isdir(custom_aws_creds_dir)
            assert os.path.islink(custom_aws_creds_dir)
            assert os.readlink(custom_aws_creds_dir) == env_dir

            # Verify that we have an s3_encrypt_key.txt file.
            # If we were called with pre_existing_s3_encrypt_key_file then the s3_encrypt_key.txt
            # file we created above (before calling the main script function) should have the same contents.
            # Otherwise, just check that it has some reasonable content, and that it is mode 400.

            assert os.path.isfile(s3_encrypt_key_file)
            with io.open(s3_encrypt_key_file, "r") as s3_encrypt_key_f:
                s3_encrypt_key = s3_encrypt_key_f.read()
                if pre_existing_s3_encrypt_key_file:
                    assert s3_encrypt_key == self.Inputs.s3_encrypt_key
                else:
                    s3_encrypt_key_file_mode = os.stat(s3_encrypt_key_file).st_mode
                    # Check that the created file mode is 400.
                    # FYI: stat.S_IFREG means regular file and stat.S_IRUSR means read access for user/owner.
                    assert s3_encrypt_key_file_mode == stat.S_IFREG | stat.S_IRUSR
                    assert 32 <= len(s3_encrypt_key) <= 128

            # Check that any secrets printed out look like they"ve been obfuscated.

            for call in mock_cli_print.call_args_list:
                args, kwargs = call
                if len(args) == 1:
                    arg = args[0]
                    if re.search(".*using.*secret.*:", arg, re.IGNORECASE):
                        assert arg.endswith("******")

    def _call_function_and_assert_exit_with_no_action(self, f):
        with mock.patch("builtins.exit") as mock_exit, \
             mock.patch("src.auto.init_custom_dir.utils.PRINT") as mock_utils_print:
            mock_exit.side_effect = Exception()
            with self.assertRaises(Exception):
                f()
            assert mock_exit.called is True
            assert mock_exit.call_count == 1
            # Check the message from the last print which should be something like: Exiting without doing anything.
            # Kinda lame.
            last_print_arg = mock_utils_print.call_args.args[0]
            assert re.search(".*exit.*without.*doing*", last_print_arg, re.IGNORECASE)

    def test_sanity(self):
        assert len(InfraDirectories.AWS_DIR) > 0
        assert os.path.isfile(InfraFiles.get_config_template_file())
        assert os.path.isfile(InfraFiles.get_secrets_template_file())
        assert re.search("\\*+$", obfuscate("ABCDEFGHI")[1:])

    def test_main(self):
        self._call_main(pre_existing_s3_encrypt_key_file=False)

    def test_main_with_pre_existing_s3_encrypt_key_file(self):
        self._call_main(pre_existing_s3_encrypt_key_file=True)

    def test_main_with_pre_existing_custom_dir(self):

        with self._setup_filesystem(self.Inputs.env_name, self.Inputs.account_number) \
                as (aws_dir, env_dir, custom_dir), \
             mock.patch("src.auto.init_custom_dir.cli.PRINT"), \
             mock.patch("src.auto.init_custom_dir.utils.PRINT"):

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

            config_json_file = os.path.join(custom_dir, "config.json")
            secrets_json_file = os.path.join(custom_dir, "secrets.json")

            # For this test case we create a pre-existing custom directory, and therefore
            # cause this process not to move forward; create it and also create dummy
            # config.json and secrets.json files and make sure we did not overwrite them.

            os.makedirs(custom_dir)
            with io.open(config_json_file, "w") as config_json_f:
                config_json_f.write(self.Inputs.dummy_json_content)
            with io.open(secrets_json_file, "w") as secrets_json_f:
                secrets_json_f.write(self.Inputs.dummy_json_content)

            # Call the script function.

            argv = self._get_standard_main_args(aws_dir, self.Inputs.env_name, custom_dir)

            # Test case if the custom directory already exists.
            # Check that we exit without doing anything.

            self._call_function_and_assert_exit_with_no_action(lambda: main(argv))

            with io.open(config_json_file, "r") as config_json_f:
                assert config_json_f.read() == self.Inputs.dummy_json_content
            with io.open(secrets_json_file, "r") as secrets_json_f:
                assert secrets_json_f.read() == self.Inputs.dummy_json_content

    def test_main_with_no_existing_env_dir(self):

        with self._setup_filesystem(self.Inputs.env_name, self.Inputs.account_number) \
                as (aws_dir, env_dir, custom_dir), \
             mock.patch("src.auto.init_custom_dir.cli.PRINT"), \
             mock.patch("src.auto.init_custom_dir.utils.PRINT"):

            # Call the script function with an env-name for which a env-dir does not exist.

            argv = self._get_standard_main_args(aws_dir, "env-name-with-no-associated-env-dir", custom_dir)
            self._call_function_and_assert_exit_with_no_action(lambda: main(argv))
            assert not os.path.exists(custom_dir)

    def test_main_when_answering_no_to_confirmation_prompt(self):

        with self._setup_filesystem(self.Inputs.env_name, self.Inputs.account_number) \
                as (aws_dir, env_dir, custom_dir), \
             mock.patch("src.auto.init_custom_dir.cli.PRINT"), \
             mock.patch("src.auto.init_custom_dir.utils.PRINT"), \
             mock.patch("builtins.input") as mock_input:

            mock_input.return_value = 'no'
            argv = self._get_standard_main_args(aws_dir, self.Inputs.env_name, custom_dir)
            self._call_function_and_assert_exit_with_no_action(lambda: main(argv))
            assert not os.path.exists(custom_dir)

    def test_main_prompt_when_missing_required_inputs(self):
        # Not yet implemented.
        # In the case of missing required inputs we actually we prompt for them.
        pass

    def test_main_exit_when_missing_required_inputs(self):
        # Not yet implemented.
        # In the case of missing required inputs,
        # even after prompting, if not given then exit with no action.
        pass
