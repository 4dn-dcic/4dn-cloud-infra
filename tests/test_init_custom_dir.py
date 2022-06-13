import io
import json
import mock
import os
import pytest
import re
import stat
import tempfile
from contextlib import contextmanager
from src.auto.init_custom_dir.cli import (get_fallback_identity, main)
from src.auto.init_custom_dir.defs import InfraDirectories, InfraFiles
from src.auto.init_custom_dir.utils import obfuscate
from dcicutils.qa_utils import printed_output as mock_print

# Tests for the main init-custom-dir script.


class Input:
    env_name = "your-env"
    account_number = "1234567890"
    s3_bucket_org = "prufrock"
    auth0_client = "0A39E193F7B74218A3F176872197D895"
    auth0_secret = "126EBFCAC9C74CD5B2CBAD7B3DCB3314"
    recaptcha_key = "5449963A45A4E9DAEDA36062405DDBE"
    recaptcha_secret = "08DEBE6BE73D49549B18CE9641D80DC5"
    deploying_iam_user = "someuser"
    s3_encrypt_key = "8F383EBE093941B5B927279F361C3002"
    dummy_json_content = "{\"dummy\": \"<dummy-content>\" }"


def _get_standard_main_argv(aws_dir: str, env_name: str, custom_dir: str, omit_arg: str = None) -> list:
    argv = ["--awsdir", aws_dir,
            "--env", env_name,
            "--out", custom_dir,
            "--s3org", Input.s3_bucket_org,
            "--auth0client", Input.auth0_client, "--auth0secret", Input.auth0_secret,
            "--recaptchakey", Input.recaptcha_key, "--recaptchasecret", Input.recaptcha_secret]
    if omit_arg and omit_arg in argv:
        arg_index = argv.index(omit_arg)
        if 0 <= arg_index < len(argv) - 1:
            del argv[arg_index + 1]
            del argv[arg_index]
    return argv


def _rummage_for_print_message(mocked_print, regular_expression):
    """
    Searches the given print mock for the/a print call whose arguments matches
    the given regular expression, and returns True if it finds (just) one
    that matches, otherwise returns False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            return True
    return False


def _rummage_for_print_message_all(mocked_print, regular_expression, predicate):
    """
    Searches the given print mock for the/a call whose argument matches
    the given regular expression and returns True iff each/every match also
    passes (gets a True return value from) the given predicate function
    with that argument, otherwise returns False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            if not predicate(value):
                return False
    return True


@contextmanager
def _setup_filesystem(env_name: str, account_number: str = None):
    """
    Sets up our directories to use in a system temporary directory,
    which gets totally cleaned up after the with-context where this is used.
    Returns (yields) a tuple with the full path names of:
    - The created AWS base directory (e.g. representing /your-home/.aws_test)
    - The created AWS environment directory (e.g. representing /your-home/.aws_test.your-env)
    - The NOT-created custom directory (e.g. representing /your-repos/4dn-cloud-infra/custom)
    If account_number is specified then also creates:
    - A test_creds.sh with an export for ACCOUNT_NUMBER will be created,
      e.g. representing /your-home/.aws_test.your-env/test_creds.sh
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        aws_dir = os.path.join(tmp_dir, ".aws_test")
        env_dir = os.path.join(tmp_dir, ".aws_test." + env_name)
        custom_dir = os.path.join(tmp_dir, "custom")
        test_creds_script_file = os.path.join(env_dir, "test_creds.sh")
        # aws_dir represents: /your-home/.aws_test
        os.makedirs(aws_dir)
        # env_dir represents: /your-home/.aws_test.your-env
        os.makedirs(env_dir)
        if account_number:
            with io.open(test_creds_script_file, "w") as test_creds_script_fp:
                # test_creds_script_file represents: /your-home/.aws_test.your-env/test_creds.sh
                test_creds_script_fp.write(f"export ACCOUNT_NUMBER={account_number}")
                test_creds_script_fp.write(f"\n")
        yield aws_dir, env_dir, custom_dir


def _call_main(pre_existing_s3_encrypt_key_file: bool = True):

    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir), \
         mock_print() as mocked_print, \
         mock.patch("src.auto.init_custom_dir.cli.os.getlogin") as mock_os_getlogin, \
         mock.patch("builtins.input") as mock_input:

        mock_os_getlogin.return_value = Input.deploying_iam_user
        mock_input.return_value = "yes"

        # This is the directory structure we are simulating;
        # well, actually creating, within a temporary directory.
        # Variable names used for each (below) in parenthesis.
        #
        #   /your-repos/4dn-cloud-infra/custom (custom_dir)
        #     ├── aws_creds@ -> /your-home/.aws_test.your-env (custom_aws_cred_dir, env_dir)
        #     │   ├── s3_encrypt_key.txt (s3_encrypt_key_file)
        #     │   └── test_creds.sh
        #     ├── config.json (config_json_file)
        #     └── secrets.json (secrets_json_file)

        custom_aws_creds_dir = os.path.join(custom_dir, "aws_creds")
        config_json_file = os.path.join(custom_dir, "config.json")
        secrets_json_file = os.path.join(custom_dir, "secrets.json")
        s3_encrypt_key_file = os.path.join(env_dir, "s3_encrypt_key.txt")

        if pre_existing_s3_encrypt_key_file:
            with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_fp:
                s3_encrypt_key_fp.write(Input.s3_encrypt_key)

        # Call the main script function.
        # Normal case where custom directory does not already exist.

        argv = _get_standard_main_argv(aws_dir, Input.env_name, custom_dir)
        main(argv)

        # Verify existence/contents of config.json file (e.g. in /your-repos/4dn-cloud-infra/custom/config.json).

        assert os.path.isfile(config_json_file)
        with io.open(config_json_file, "r") as config_json_fp:
            config_json = json.load(config_json_fp)
            assert config_json["account_number"] == Input.account_number
            assert config_json["s3.bucket.org"] == Input.s3_bucket_org
            assert config_json["deploying_iam_user"] == Input.deploying_iam_user
            assert config_json["identity"] == "C4DatastoreYourEnvApplicationConfiguration"
            assert config_json["ENCODED_ENV_NAME"] == Input.env_name

        # Verify existence/contents of secrets.json file (e.g. in /your-repos/4dn-cloud-infra/custom/secrets.json).

        assert os.path.isfile(secrets_json_file)
        with io.open(secrets_json_file, "r") as secrets_json_fp:
            secrets_json = json.load(secrets_json_fp)
            assert secrets_json["Auth0Client"] == Input.auth0_client
            assert secrets_json["Auth0Secret"] == Input.auth0_secret
            assert secrets_json["reCaptchaKey"] == Input.recaptcha_key
            assert secrets_json["reCaptchaSecret"] == Input.recaptcha_secret

        # Verify that we have custom/aws_creds directory (e.g. in /your-repos/4dn-cloud-infra/custom/config.json).
        # And that it is actually a symlink to the AWS environment directory (e.g. to /your-home/.aws_test.your-env).

        assert os.path.isdir(custom_aws_creds_dir)
        assert os.path.islink(custom_aws_creds_dir)
        assert os.readlink(custom_aws_creds_dir) == env_dir

        # Verify that we have an s3_encrypt_key.txt file.
        # If we were called with pre_existing_s3_encrypt_key_file then the s3_encrypt_key.txt
        # file we created above (before calling the main script function) should have the same contents.
        # Otherwise, just check that it has some reasonable content, and that it is mode 400.

        assert os.path.isfile(s3_encrypt_key_file)
        with io.open(s3_encrypt_key_file, "r") as s3_encrypt_key_fp:
            s3_encrypt_key = s3_encrypt_key_fp.read()
            if pre_existing_s3_encrypt_key_file:
                assert s3_encrypt_key == Input.s3_encrypt_key
            else:
                s3_encrypt_key_file_mode = os.stat(s3_encrypt_key_file).st_mode
                # Check that the created file mode is 400.
                # FYI: stat.S_IFREG means regular file and stat.S_IRUSR means read access for user/owner.
                assert s3_encrypt_key_file_mode == stat.S_IFREG | stat.S_IRUSR
                assert 32 <= len(s3_encrypt_key) <= 128

        # Check that any secrets printed out look like they"ve been obfuscated.

        assert _rummage_for_print_message_all(
            mocked_print, ".*using.*secret.*", lambda arg: arg.endswith("*******"))


def _call_function_and_assert_exit_with_no_action(f, interrupt: bool = False):
    with mock_print() as mocked_print, \
         mock.patch("builtins.exit") as mock_exit:
        mock_exit.side_effect = Exception()
        with pytest.raises(Exception):
            f()
        if interrupt:
            assert _rummage_for_print_message(mocked_print, ".*interrupt.*") is True
        assert mock_exit.called is True
        # Check the message from the last print which should be something like: Exiting without doing anything.
        # Kinda lame.
        assert _rummage_for_print_message(mocked_print, ".*exit.*without.*doing*") is True


def test_sanity():
    assert re.search("\\*+$", obfuscate("ABCDEFGHI")[1:])


def test_paths():
    assert len(InfraDirectories.AWS_DIR) > 0
    assert os.path.isfile(InfraFiles.get_config_template_file())
    assert os.path.isfile(InfraFiles.get_secrets_template_file())
    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir):
        assert InfraFiles.get_test_creds_script_file(env_dir) == os.path.join(env_dir, "test_creds.sh")
        assert InfraFiles.get_config_file(custom_dir) == os.path.join(custom_dir, "config.json")
        assert InfraFiles.get_secrets_file(custom_dir) == os.path.join(custom_dir, "secrets.json")
        assert InfraFiles.get_s3_encrypt_key_file(custom_dir) == \
               os.path.join(custom_dir, "aws_creds/s3_encrypt_key.txt")
        assert InfraDirectories.get_custom_aws_creds_dir(custom_dir) == os.path.join(custom_dir, "aws_creds")


def test_main_vanilla():
    _call_main(pre_existing_s3_encrypt_key_file=False)


def test_main_with_pre_existing_s3_encrypt_key_file():
    _call_main(pre_existing_s3_encrypt_key_file=True)


def test_main_with_pre_existing_custom_dir():

    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir):

        # This is the directory structure we are simulating;
        # well, actually creating, within a temporary directory.
        # Variable names used for each (below) in parenthesis.
        #
        #   /your-repos/4dn-cloud-infra/custom (custom_dir)
        #     ├── aws_creds@ -> /your-home/.aws_test.your-env (custom_aws_cred_dir, env_dir)
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
        with io.open(config_json_file, "w") as config_json_fp:
            config_json_fp.write(Input.dummy_json_content)
        with io.open(secrets_json_file, "w") as secrets_json_fp:
            secrets_json_fp.write(Input.dummy_json_content)

        # Call the script function.

        argv = _get_standard_main_argv(aws_dir, Input.env_name, custom_dir)

        # Test case if the custom directory already exists.
        # Check that we exit without doing anything.

        _call_function_and_assert_exit_with_no_action(lambda: main(argv))

        with io.open(config_json_file, "r") as config_json_fp:
            assert config_json_fp.read() == Input.dummy_json_content
        with io.open(secrets_json_file, "r") as secrets_json_fp:
            assert secrets_json_fp.read() == Input.dummy_json_content


def test_main_with_no_existing_env_dir():

    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir):

        # Call the script function with an env-name for which a env-dir does not exist.

        argv = _get_standard_main_argv(aws_dir, "env-name-with-no-associated-env-dir", custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))
        assert not os.path.exists(custom_dir)


def test_main_when_answering_no_to_confirmation_prompt():

    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir), \
         mock.patch("builtins.input") as mock_input:
        mock_input.return_value = 'no'
        argv = _get_standard_main_argv(aws_dir, Input.env_name, custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))
        assert not os.path.exists(custom_dir)


def _test_main_exit_with_no_action_on_missing_required_input(omit_required_arg: str):
    # When a required input is missing we prompt for it and if still not specified (empty)
    # then we exit with no action. Test for this case here.
    account_number = Input.account_number
    if omit_required_arg == "--account":
        # If we are omitting account number then do not create test_creds.sh with ACCOUNT_NUMBER.
        account_number = None
    with _setup_filesystem(Input.env_name, account_number) as (aws_dir, env_dir, custom_dir), \
         mock.patch("builtins.input") as mock_input:
        argv = _get_standard_main_argv(aws_dir, Input.env_name, custom_dir, omit_arg=omit_required_arg)
        mock_input.side_effect = [""]  # return value for prompt for required arg
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))
    pass


def test_main_exit_with_no_action_on_missing_required_input_s3org():
    _test_main_exit_with_no_action_on_missing_required_input("--s3org")


def test_main_exit_with_no_action_on_missing_required_input_auth0client():
    _test_main_exit_with_no_action_on_missing_required_input("--auth0client")


def test_main_exit_with_no_action_on_missing_required_input_auth0secret():
    _test_main_exit_with_no_action_on_missing_required_input("--auth0secret")


def test_main_exit_with_no_action_on_missing_required_input_account():
    _test_main_exit_with_no_action_on_missing_required_input("--account")


def test_main_with_keyboard_interrupt():
    with _setup_filesystem(Input.env_name, Input.account_number) as (aws_dir, env_dir, custom_dir), \
         mock.patch("builtins.input") as mock_input:
        mock_input.side_effect = [KeyboardInterrupt]
        argv = _get_standard_main_argv(aws_dir, Input.env_name, custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv), interrupt=True)
        assert not os.path.exists(custom_dir)


def test_get_fallback_identity():
    assert get_fallback_identity("your-test-env") == "C4DatastoreYourTestEnvApplicationConfiguration"


def test_what_else_i_think_we_have_most_important_cases_covered():
    # Not yet implemented.
    pass
