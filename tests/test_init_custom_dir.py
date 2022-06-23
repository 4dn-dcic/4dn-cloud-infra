import io
import json
import mock
import os
import pytest
import re
import stat
import tempfile
from typing import Callable
from contextlib import contextmanager
from dcicutils.qa_utils import printed_output as mock_print
from src.auto.init_custom_dir.cli import (get_fallback_identity, main)
from src.auto.utils.locations import InfraDirectories, InfraFiles
from src.auto.utils.misc_utils import obfuscate

# Tests for the main init-custom-dir script.


class Input:
    aws_credentials_name = "your-credentials-name"
    account_number = "1234567890"
    s3_bucket_org = "prufrock"
    auth0_client = "0A39E193F7B74218A3F176872197D895"
    auth0_secret = "126EBFCAC9C74CD5B2CBAD7B3DCB3314"
    recaptcha_key = "5449963A45A4E9DAEDA36062405DDBE"
    recaptcha_secret = "08DEBE6BE73D49549B18CE9641D80DC5"
    deploying_iam_user = "someuser"
    s3_encrypt_key = "8F383EBE093941B5B927279F361C3002"
    s3_bucket_encryption = True
    dummy_json_content = "{\"dummy\": \"<dummy-content>\" }"


def _get_standard_main_argv(aws_dir: str, aws_credentials_name: str, custom_dir: str, omit_arg: str = None) -> list:
    argv = ["--awsdir", aws_dir,
            "--credentials", aws_credentials_name,
            "--out", custom_dir,
            "--s3org", Input.s3_bucket_org,
            "--s3encrypt",
            "--auth0client", Input.auth0_client, "--auth0secret", Input.auth0_secret,
            "--recaptchakey", Input.recaptcha_key, "--recaptchasecret", Input.recaptcha_secret]
    if omit_arg and omit_arg in argv:
        arg_index = argv.index(omit_arg)
        if 0 <= arg_index < len(argv) - 1:
            del argv[arg_index + 1]
            del argv[arg_index]
    return argv


def _rummage_for_print_message(mocked_print, regular_expression: str):
    """
    Searches the given print mock for the/a print call whose arguments matches
    the given regular expression, and returns True if it finds (just) one
    that matches, otherwise returns False.
    """
    for value in mocked_print.lines:
        if re.search(regular_expression, value, re.IGNORECASE):
            return True
    return False


def _rummage_for_print_message_all(mocked_print, regular_expression: str, predicate: Callable):
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
def _setup_filesystem(aws_credentials_name: str, account_number: str = None):
    """
    Sets up our directories to use in a system temporary directory,
    which gets totally cleaned up after the with-context where this is used.
    Returns (yields) a tuple with the full path names of:
    - The created AWS base directory (e.g. representing /your-home/.aws_test)
    - The created AWS credentials directory (e.g. representing /your-home/.aws_test.<your-credentials-name>)
    - The NOT-created custom directory (e.g. representing /your-repos/4dn-cloud-infra/custom)
    If account_number is specified then also creates:
    - A test_creds.sh with an export for ACCOUNT_NUMBER will be created,
      e.g. representing /your-home/.aws_test.<your-credentials-name>/test_creds.sh
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        aws_dir = os.path.join(tmp_dir, ".aws_test")
        aws_credentials_dir = os.path.join(tmp_dir, ".aws_test." + aws_credentials_name)
        custom_dir = os.path.join(tmp_dir, "custom")
        test_creds_script_file = os.path.join(aws_credentials_dir, "test_creds.sh")
        # aws_dir represents: /your-home/.aws_test
        os.makedirs(aws_dir)
        # aws_credentials_dir represents: /your-home/.aws_test.<your-credentials-name>
        os.makedirs(aws_credentials_dir)
        if account_number:
            with io.open(test_creds_script_file, "w") as test_creds_script_fp:
                # test_creds_script_file represents: /your-home/.aws_test.<your-credentials-name>/test_creds.sh
                test_creds_script_fp.write(f"export ACCOUNT_NUMBER={account_number}")
                test_creds_script_fp.write(f"\n")
        yield aws_dir, aws_credentials_dir, custom_dir


def _call_main(pre_existing_s3_encrypt_key_file: bool = True) -> None:

    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir), \
         mock_print() as mocked_print, \
         mock.patch("src.auto.init_custom_dir.cli.os.getlogin") as mocked_os_getlogin, \
         mock.patch("builtins.input") as mocked_input:

        mocked_os_getlogin.return_value = Input.deploying_iam_user
        mocked_input.return_value = "yes"

        # This is the directory structure we are simulating;
        # well, actually creating, within a temporary directory.
        # Variable names used for each (below) in parenthesis.
        #
        #   /your-repos/4dn-cloud-infra/custom (custom_dir)
        #     ├── aws_creds@ -> /your-home/.aws_test.<your-credentials-name> (custom_aws_cred_dir, aws_credentials_dir)
        #     │   ├── s3_encrypt_key.txt (s3_encrypt_key_file)
        #     │   └── test_creds.sh
        #     ├── config.json (config_json_file)
        #     └── secrets.json (secrets_json_file)
        custom_aws_creds_dir = os.path.join(custom_dir, "aws_creds")
        config_json_file = os.path.join(custom_dir, "config.json")
        secrets_json_file = os.path.join(custom_dir, "secrets.json")
        s3_encrypt_key_file = os.path.join(aws_credentials_dir, "s3_encrypt_key.txt")

        if pre_existing_s3_encrypt_key_file:
            with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_fp:
                s3_encrypt_key_fp.write(Input.s3_encrypt_key)

        # Call the main script function.
        # Normal case where custom directory does not already exist.
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir)
        main(argv)

        # Verify existence/contents of config.json file (e.g. in /your-repos/4dn-cloud-infra/custom/config.json).
        assert os.path.isfile(config_json_file)
        with io.open(config_json_file, "r") as config_json_fp:
            config_json = json.load(config_json_fp)
            assert config_json["account_number"] == Input.account_number
            assert config_json["s3.bucket.org"] == Input.s3_bucket_org
            assert config_json["deploying_iam_user"] == Input.deploying_iam_user
            assert config_json["identity"] == "C4DatastoreYourCredentialsNameApplicationConfiguration"
            assert config_json["ENCODED_ENV_NAME"] == Input.aws_credentials_name
            assert config_json["s3.bucket.encryption"] == Input.s3_bucket_encryption

        # Verify existence/contents of secrets.json file (e.g. in /your-repos/4dn-cloud-infra/custom/secrets.json).
        assert os.path.isfile(secrets_json_file)
        with io.open(secrets_json_file, "r") as secrets_json_fp:
            secrets_json = json.load(secrets_json_fp)
            assert secrets_json["Auth0Client"] == Input.auth0_client
            assert secrets_json["Auth0Secret"] == Input.auth0_secret
            assert secrets_json["reCaptchaKey"] == Input.recaptcha_key
            assert secrets_json["reCaptchaSecret"] == Input.recaptcha_secret

        # Verify that we have custom/aws_creds directory (e.g. in /your-repos/4dn-cloud-infra/custom/config.json).
        # And that it is actually a symlink to the AWS credentials
        # directory, e.g. to /your-home/.aws_test.<your-credentials-name>.
        assert os.path.isdir(custom_aws_creds_dir)
        assert os.path.islink(custom_aws_creds_dir)
        assert os.readlink(custom_aws_creds_dir) == aws_credentials_dir

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
        assert _rummage_for_print_message_all(
            mocked_print, ".*using.*secret.*",
            lambda arg: Input.auth0_secret not in arg and Input.recaptcha_secret not in arg)


def _call_function_and_assert_exit_with_no_action(f, interrupt: bool = False) -> None:
    with mock_print() as mocked_print, \
         mock.patch("builtins.exit") as mocked_exit:
        mocked_exit.side_effect = Exception()
        with pytest.raises(Exception):
            f()
        if interrupt:
            assert _rummage_for_print_message(mocked_print, ".*interrupt.*") is True
        assert mocked_exit.called is True
        # Check the message from the last print which should be something like: Exiting without doing anything.
        # Kinda lame.
        assert _rummage_for_print_message(mocked_print, ".*exit.*without.*doing*") is True


def test_sanity() -> None:
    assert re.search("\\*+$", obfuscate("ABCDEFGHI")[1:])


def test_directories_and_files() -> None:
    assert len(InfraDirectories.AWS_DIR) > 0
    assert os.path.isfile(InfraFiles.get_config_template_file())
    assert os.path.isfile(InfraFiles.get_secrets_template_file())
    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir):
        assert InfraFiles.get_test_creds_script_file(aws_credentials_dir) == \
               os.path.join(aws_credentials_dir, "test_creds.sh")
        assert InfraFiles.get_config_file(custom_dir) == os.path.join(custom_dir, "config.json")
        assert InfraFiles.get_secrets_file(custom_dir) == os.path.join(custom_dir, "secrets.json")
        assert InfraFiles.get_s3_encrypt_key_file(custom_dir) == \
               os.path.join(custom_dir, "aws_creds/s3_encrypt_key.txt")
        assert InfraDirectories.get_custom_aws_creds_dir(custom_dir) == os.path.join(custom_dir, "aws_creds")


def test_main_vanilla() -> None:
    _call_main(pre_existing_s3_encrypt_key_file=False)


def test_main_with_pre_existing_s3_encrypt_key_file() -> None:
    _call_main(pre_existing_s3_encrypt_key_file=True)


def test_main_with_pre_existing_custom_dir() -> None:

    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir):

        # This is the directory structure we are simulating;
        # well, actually creating, within a temporary directory.
        # Variable names used for each (below) in parenthesis.
        #
        #   /your-repos/4dn-cloud-infra/custom (custom_dir)
        #     ├── aws_creds@ -> /your-home/.aws_test.<your-credentials-name> (custom_aws_cred_dir, aws_credentials_dir)
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
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir)

        # Test case if the custom directory already exists.
        # Check that we exit without doing anything.
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))

        with io.open(config_json_file, "r") as config_json_fp:
            assert config_json_fp.read() == Input.dummy_json_content
        with io.open(secrets_json_file, "r") as secrets_json_fp:
            assert secrets_json_fp.read() == Input.dummy_json_content


def test_main_with_no_existing_aws_credentials_dir() -> None:

    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir):
        # Call the script function with an aws_credentials_name for which an aws_credentials_dir does not exist.
        argv = _get_standard_main_argv(aws_dir, "aws-credentials-name-with-no-associated--dir", custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))
        assert not os.path.exists(custom_dir)


def test_main_when_answering_no_to_confirmation_prompt() -> None:

    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir), \
         mock.patch("builtins.input") as mocked_input:
        mocked_input.return_value = 'no'
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))
        assert not os.path.exists(custom_dir)


def _test_main_exit_with_no_action_on_missing_required_input(omit_required_arg: str) -> None:
    # When a required input is missing we prompt for it and if still not specified (empty)
    # then we exit with no action. Test for this case here.
    account_number = Input.account_number
    if omit_required_arg == "--account":
        # If we are omitting account number then do not create test_creds.sh with ACCOUNT_NUMBER.
        account_number = None
    with _setup_filesystem(
         Input.aws_credentials_name, account_number) as (aws_dir, aws_credentials_dir, custom_dir), \
         mock.patch("builtins.input") as mocked_input:
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir, omit_arg=omit_required_arg)
        mocked_input.side_effect = [""]  # return value for prompt for required arg
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))


def test_main_exit_with_no_action_on_missing_required_input_s3org() -> None:
    _test_main_exit_with_no_action_on_missing_required_input("--s3org")


def test_main_exit_with_no_action_on_missing_required_input_auth0client() -> None:
    _test_main_exit_with_no_action_on_missing_required_input("--auth0client")


def test_main_exit_with_no_action_on_missing_required_input_auth0secret() -> None:
    _test_main_exit_with_no_action_on_missing_required_input("--auth0secret")


def test_main_exit_with_no_action_on_missing_required_input_account() -> None:
    _test_main_exit_with_no_action_on_missing_required_input("--account")


def test_main_exit_with_no_action_on_missing_required_input_identity() -> None:
    # This tests failure of get_identity_fallback.
    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir), \
         mock.patch("src.auto.init_custom_dir.cli.get_fallback_identity") as mocked_get_fallback_identity:
        mocked_get_fallback_identity.return_value = None
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv))


def test_main_with_keyboard_interrupt() -> None:
    with _setup_filesystem(
         Input.aws_credentials_name, Input.account_number) as (aws_dir, aws_credentials_dir, custom_dir), \
         mock.patch("builtins.input") as mocked_input:
        mocked_input.side_effect = [KeyboardInterrupt]
        argv = _get_standard_main_argv(aws_dir, Input.aws_credentials_name, custom_dir)
        _call_function_and_assert_exit_with_no_action(lambda: main(argv), interrupt=True)
        assert not os.path.exists(custom_dir)


def test_get_fallback_identity() -> None:
    assert get_fallback_identity("your-test") == "C4DatastoreYourTestApplicationConfiguration"


def test_what_else_i_think_we_have_most_important_cases_covered() -> None:
    # Not yet implemented.
    pass
