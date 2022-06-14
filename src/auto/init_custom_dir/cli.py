# Script to setup the local custom config directory for the 4dn-cloud-infra repo.
# For example like this:
#
#   /your-repos/4dn-cloud-infra/custom
#     ├── config.json
#     ├── secrets.json
#     └── aws_creds@ ─> /your-home/.aws_test.cgap-supertest/
#         ├── credentials
#         ├── test_creds.sh
#         └── s3_encrypt_key.txt
#
# The credentials and test_creds.sh files ared assumed to already exist;
# the former is NOT used here; the latter actually IS used here but ONLY
# to get a fallback value for the account_number from the ACCOUNT_NUMBER
# environment variable there, if not specified via command-line --account.
#
# The config.json and secrets.json files are created from existing template
# files and inputs from the user to this script.
#
# See the help in argparse for ommand-line options.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - glob.glob
#     - io.open
#     - os.chmod
#     - os.getcwd
#     - os.getlogin
#     - os.listdir
#     - os.makedirs
#     - os.path.abspath
#     - os.path.basename
#     - os.path.dirname
#     - os.path.exists
#     - os.path.expanduser
#     - os.path.isdir
#     - os.path.isfile
#     - os.path.islink
#     - os.path.join
#     - os.readlink
#     - os.symlink
#   - shell via:
#     - subprocess.check_output (to execute test_cred.sh)
#   - command-line arguments via:
#     os.argv

import argparse
import io
import os
import stat
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from .aws_credentials_info import AwsCredentialsInfo
from .utils import (
    exit_with_no_action,
    expand_json_template_file,
    generate_s3_encrypt_key,
    obfuscate,
    print_directory_tree,
    read_env_variable_from_subshell,
    setup_and_action
)
from .defs import (
    ConfigTemplateVars,
    InfraDirectories,
    EnvVars,
    InfraFiles,
    SecretsTemplateVars
)
from ...names import Names


def get_fallback_account_number(aws_credentials_dir: str) -> str:
    """
    Obtains/returns fallback account_number value by executing the test_creds.sh
    file for the chosen AWS credentials (in a sub-shell) and grabbing the value
    of the ACCOUNT_NUMBER environment value which is likely to be set there.

    :param aws_credentials_dir: AWS credentials directory path.
    :return: Account number from test_creds.sh if found otherwise None.
    """
    test_creds_script_file = InfraFiles.get_test_creds_script_file(aws_credentials_dir)
    return read_env_variable_from_subshell(test_creds_script_file, EnvVars.ACCOUNT_NUMBER)


def get_fallback_deploying_iam_user() -> str:
    """
    Obtains/returns fallback deploying_iam_user value, simply from the OS environment.

    :return: Username as found by os.getlogin().
    """
    return os.getlogin()


def get_fallback_identity(aws_credentials_name: str) -> str:
    """
    Obtains/returns the 'identity', i.e. the global application configuration name using
    the same code that 4dn-cloud-infra code does (see C4Datastore.application_configuration_secret).
    Had to do some refactoring to get this working (see names.py).

    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :return: Identity (global application configuration name) as gotten from the main 4dn-cloud-infra code.
    """
    try:
        identity_value = Names.application_configuration_secret(aws_credentials_name)
    except Exception:
        identity_value = None
    return identity_value


def validate_aws_credentials_info(
        aws_dir: str, aws_credentials_name: str, confirm: bool = True, debug: bool = False) -> (str, str):
    """
    Validates the given AWS directory and AWS credentials name and returns
    the AWS credentials name and full path to the associated AWS credentials directory.
    If the AWS credentials name is not given and there is a current one in
    effect then we prompt/ask if they want to use that one; exit on error (if not set).

    :param aws_dir: Specified AWS base directory (default: ~/.aws_test from InfraDirectories.AWS_DIR).
    :param aws_credentials_name: Specified AWS credentials name.
    :param confirm: False to NOT interactively confirm yes/no to confirmation prompts.
    :param debug: True for debugging output.
    :return: Tuple with AWS credentials name and full path to associated AWS credentials directory.
    """

    # Since we allow the base ~/.aws_test to be changed
    # via --awsdir we best check that it is not passed as empty.
    # Note the default aws_dir comes from InfraDirectories.AWS_DIR.
    aws_dir = aws_dir.strip()
    if not aws_dir:
        exit_with_no_action(f"An ~/.aws directory must be specified; default is: {InfraDirectories.AWS_DIR}")

    # Get basic AWS credentials info.

    aws_credentials_info = None
    try:
        aws_credentials_info = AwsCredentialsInfo(aws_dir)
    except Exception as e:
        exit_with_no_action(str(e))

    if debug:
        PRINT(f"DEBUG: AWS base directory: {aws_credentials_info.dir}")
        PRINT(f"DEBUG: Available AWS credentials names: {aws_credentials_info.available_credentials_names}")
        PRINT(f"DEBUG: Current AWS credentials name: {aws_credentials_info.selected_credentials_name}")

    def print_available_aws_credentials_names():
        PRINT("Available credentials names:")
        for available_credentials_name in sorted(aws_credentials_info.available_credentials_names):
            PRINT(f"* {available_credentials_name} -> {aws_credentials_info.get_credentials_dir(available_credentials_name)}")

    # Make sure the given AWS credentials name is good. Required but just in case
    # not set anyways, check current credentials, and if set, and ask them if they
    # want to use that. But don't do this interactive thing if --no-confirm option
    # given, rather just error out on the next if statement after this one below.
    aws_credentials_name = aws_credentials_name.strip()
    if not aws_credentials_name and confirm:
        if not aws_credentials_info.selected_credentials_name:
            exit_with_no_action("No AWS credentials name specified. Use the --env option to specify this.")
        else:
            aws_credentials_name = aws_credentials_info.selected_credentials_name
            PRINT(f"No AWS credentials name specified. Use the --env option to specify this.")
            PRINT(f"Though it looks like your current AWS credentials name is:"
                  f"{aws_credentials_info.selected_credentials_name}")
            if not yes_or_no(f"Do you want to use this ({aws_credentials_info.selected_credentials_name})?"):
                print_available_aws_credentials_names()
                exit_with_no_action()

    # Make sure the given AWS credentials name actually
    # exists as a ~/.aws_test.<aws-credentials-name> directory.
    if not aws_credentials_name or aws_credentials_name not in aws_credentials_info.available_credentials_names:
        PRINT(f"No AWS credentials for this name exists: {aws_credentials_name}")
        if aws_credentials_info.available_credentials_names:
            print_available_aws_credentials_names()
            exit_with_no_action("Choose one of the above AWS credentials using the --env option.")
        else:
            exit_with_no_action(
                f"No AWS credentials names/directories found at all.",
                f"You need to have at least one {aws_credentials_info.dir}.<aws-credentials-name> directory setup.")

    aws_credentials_dir = aws_credentials_info.get_credentials_dir(aws_credentials_name)

    PRINT(f"Setting up 4dn-cloud-infra local custom config directory for AWS credentials: {aws_credentials_name}")
    PRINT(f"Your AWS credentials directory: {aws_credentials_dir}")

    return aws_credentials_name, aws_credentials_dir


def validate_custom_dir(custom_dir: str) -> str:
    """
    Validates the given custom directory and returns its full path.
    Prompts for this value if not set; exit on error (if not set).

    :param custom_dir: Specified custom directory.
    :return: Full path to custom directory.
    """
    custom_dir = custom_dir.strip()
    if not custom_dir:
        exit_with_no_action("You must specify a custom output directory using the --out option.")

    custom_dir = InfraDirectories.get_custom_dir(custom_dir)
    if os.path.exists(custom_dir):
        file_or_directory = 'directory' if os.path.isdir(custom_dir) else 'file'
        exit_with_no_action(
            f"A custom {file_or_directory} already exists: {custom_dir}")

    PRINT(f"Using custom directory: {custom_dir}")
    return custom_dir


def validate_account_number(account_number: str, aws_credentials_dir: str, debug: bool = False) -> str:
    """
    Validates the given account number (if specified), and returns it if/when set.
    If not specified we try to get it from test_creds.sh.
    Prompts for this value if not set; exit on error (if not set).
    We get the default/fallback value for this from test_creds.sh if present.

    :param account_number: Account number value.
    :param aws_credentials_dir: Full path to AWS credentials directory.
    :param debug: True for debugging output.
    :return: Account number value.
    """
    if not account_number:
        if debug:
            PRINT(f"DEBUG: Trying to read {EnvVars.ACCOUNT_NUMBER} from:"
                  f"{InfraFiles.get_test_creds_script_file(aws_credentials_dir)}")
        account_number = get_fallback_account_number(aws_credentials_dir)
        if not account_number:
            account_number = input("Or enter your account number: ").strip()
            if not account_number:
                exit_with_no_action(f"You must specify an account number. Use the --account option.")
    PRINT(f"Using account number: {account_number}")
    return account_number


def validate_deploying_iam_user(deploying_iam_user: str) -> str:
    """
    Validates the given deploying IAM username and returns it if/when set.
    Prompts for this value if not set; exit on error (if not set).
    We get the default/fallabck value from the current system username.

    :param deploying_iam_user: Deploying IAM username value.
    :return: Deploying IAM username value.
    """
    if not deploying_iam_user:
        deploying_iam_user = get_fallback_deploying_iam_user()
        if not deploying_iam_user:
            PRINT("Cannot determine deploying IAM username. Use the --username option.")
            deploying_iam_user = input("Or enter your deploying IAM username: ").strip()
            if not deploying_iam_user:
                exit_with_no_action(f"You must specify a deploying IAM username. Use the --username option.")
    PRINT(f"Using deploying IAM username: {deploying_iam_user}")
    return deploying_iam_user


def validate_identity(identity: str, aws_credentials_name: str) -> str:
    """
    Validates the given identity (i.e. GAC name) and returns it if/when set.
    Prompts for this value if not set; exit on error (if not set).
    We get the default value from this from 4dn-cloud-infra code.

    :param identity: Identity (i.e. GAC name) value.
    :param aws_credentials_name: AWS environment name (e.g. cgap-supertest).
    :return: Identity (i.e. GAC name) value.
    """
    if not identity:
        identity = get_fallback_identity(aws_credentials_name)
        if not identity:
            PRINT("Cannot determine global application configuration name. Use the --identity option.")
            identity = input("Or enter your global application configuration name: ").strip()
            if not identity:
                exit_with_no_action(
                    f"You must specify a global application configuration name. Use the --identity option.")
    PRINT(f"Using global application configuration name: {identity}")
    return identity


def validate_s3_bucket_org(s3_bucket_org: str) -> str:
    """
    Validates the given S3 bucket organization name and returns it if/when set.
    Prompts for this value if not set; exit on error (if not set).

    :param s3_bucket_org: S3 bucket organization value.
    :return: S3 bucket organization value.
    """
    if not s3_bucket_org:
        PRINT("You must specify an S3 bucket organization name. Use the --s3org option.")
        s3_bucket_org = input("Or enter your S3 bucket organization name: ").strip()
        if not s3_bucket_org:
            exit_with_no_action(f"You must specify an S3 bucket organization. Use the --s3org option.")
    PRINT(f"Using S3 bucket organization name: {s3_bucket_org}")
    return s3_bucket_org


def validate_auth0(auth0_client: str, auth0_secret: str) -> (str, str):
    """
    Validates the given Auth0 client/secret and returns them if/when set.
    Prompts for this value if not set; exit on error (if not set).

    :param auth0_client: Auth0 client value.
    :param auth0_secret: Auth0 secret value.
    :return: Tuple with Auth0 client and secret values.
    """
    if not auth0_client:
        PRINT("You must specify an Auth0 client ID using the --auth0client option.")
        auth0_client = input("Or enter your Auth0 client ID: ").strip()
        if not auth0_client:
            exit_with_no_action(f"You must specify an Auth0 client. Use the --auth0client option.")
    PRINT(f"Using Auth0 client: {auth0_client}")

    if not auth0_secret:
        PRINT("You must specify a Auth0 secret using the --auth0secret option.")
        auth0_secret = input("Or enter your Auth0 secret ID: ").strip()
        if not auth0_secret:
            exit_with_no_action(f"You must specify an Auth0 secret. Use the --auth0secret option.")
        PRINT(f"Using Auth0 secret: {auth0_secret}")
    else:
        PRINT(f"Using Auth0 secret: {obfuscate(auth0_secret)}")

    return auth0_client, auth0_secret


def validate_recaptcha(recaptcha_key: str, recaptcha_secret: str) -> (str, str):
    """
    Validates the given reCAPTCHA key/secret and returns them if/when set.
    Does not prompt for this value if not set as not required.
    So this really just prints these values if given.

    :param recaptcha_key: reCAPTCHA key value.
    :param recaptcha_secret: reCAPTCHA secret value.
    :return: Tuple with reCAPTCHA key and secret values.
    """
    if recaptcha_key:
        PRINT(f"Using CAPTCHA key: {recaptcha_key}")
    if recaptcha_secret:
        PRINT(f"Using reCAPTCHA secret: {obfuscate(recaptcha_secret)}")
    return recaptcha_key, recaptcha_secret


def write_json_file_from_template(
        output_file: str, template_file: str, substitutions: dict, debug: bool = False) -> None:
    """
    Writes to the given JSON file the contents of the given
    template JSON file with the given substitutions expanded.
    Uses the dcicutils.misc_utils.json_leaf_subst (from utils.expand_json_template_file) for this.
    May exit on error.

    :param output_file: Full path to the output JSON file.
    :param template_file: Full path to the input template JSON file.
    :param substitutions: Substitutions to use in template expansion.
    :param debug: True for debugging output.
    """
    if debug:
        PRINT(f"DEBUG: Expanding template file: {template_file}")
    if not os.path.isfile(template_file):
        exit_with_no_action(f"ERROR: Cannot find template file! {template_file}")
    PRINT(f"Creating file: {output_file}")
    expand_json_template_file(template_file, output_file, substitutions)


def write_config_json_file(custom_dir: str, substitutions: dict, debug: bool = False) -> None:
    """
    Writes the config.json file in given custom directory based on our template and given substitutions.
    Uses the dcicutils.misc_utils.json_leaf_subst (from utils.expand_json_template_file) for this.
    May exit on error.

    :param custom_dir: Full path to the custom directory.
    :param substitutions: Substitutions to use in template expansion.
    :param debug: True for debugging output.
    """
    config_file = InfraFiles.get_config_file(custom_dir)
    config_template_file = InfraFiles.get_config_template_file()
    write_json_file_from_template(config_file, config_template_file, substitutions, debug)


def write_secrets_json_file(custom_dir: str, substitutions: dict, debug: bool = False) -> None:
    """
    Writes the secrets.json file in given custom directory based on our template and given substitutions.
    Uses the dcicutils.misc_utils.json_leaf_subst (from utils.expand_json_template_file) for this.
    May exit on error.

    :param custom_dir: Full path to the custom directory.
    :param substitutions: Substitutions to use in template expansion.
    :param debug: True for debugging output.
    """
    secrets_file = InfraFiles.get_secrets_file(custom_dir)
    secrets_template_file = InfraFiles.get_secrets_template_file()
    write_json_file_from_template(secrets_file, secrets_template_file, substitutions, debug)


def write_s3_encrypt_key_file(custom_dir: str, s3_encrypt_key: str) -> None:
    """
    Writes the s3_encrypt_key.txt file in the given custom directory with the given value.
    Will NOT overwrite if this file already exists!

    :param custom_dir: Full path to the custom directory.
    :param s3_encrypt_key: S3 encryption key value.
    """
    s3_encrypt_key_file = InfraFiles.get_s3_encrypt_key_file(custom_dir)
    if os.path.exists(s3_encrypt_key_file):
        PRINT(f"S3 encrypt file already exists: {s3_encrypt_key_file}")
        PRINT("Will NOT overwrite this file! Generated S3 encryption key not used.")
    else:
        PRINT(f"Creating S3 encrypt file: {s3_encrypt_key_file}")
        with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_fp:
            PRINT(s3_encrypt_key, file=s3_encrypt_key_fp)
        os.chmod(s3_encrypt_key_file, stat.S_IRUSR)


def init_custom_dir(aws_dir, aws_credentials_name, custom_dir, account_number,
                    deploying_iam_user, identity, s3_bucket_org, auth0_client, auth0_secret,
                    recaptcha_key, recaptcha_secret, confirm, debug):

    with setup_and_action() as setup_and_action_state:

        if debug:
            PRINT(f"DEBUG: Current directory: {os.getcwd()}")
            PRINT(f"DEBUG: Current username: {os.getlogin()}")
            PRINT(f"DEBUG: Script directory: {InfraDirectories.THIS_SCRIPT_DIR}")

        # Validate/gather all the inputs.
        aws_credentials_name, aws_credentials_dir = \
            validate_aws_credentials_info(aws_dir, aws_credentials_name, confirm, debug)
        custom_dir = validate_custom_dir(custom_dir)
        account_number = validate_account_number(account_number, aws_credentials_dir, debug)
        deploying_iam_user = validate_deploying_iam_user(deploying_iam_user)
        identity = validate_identity(identity, aws_credentials_name)
        s3_bucket_org = validate_s3_bucket_org(s3_bucket_org)
        auth0_client, auth0_secret = validate_auth0(auth0_client, auth0_secret)
        recaptcha_key, recaptcha_secret = validate_recaptcha(recaptcha_key, recaptcha_secret)

        # Generate S3 encryption key.
        # Though we will NOT overwrite s3_encrypt_key.txt if it already exists, below.
        s3_encrypt_key = generate_s3_encrypt_key()
        PRINT(f"Generating S3 encryption key: {obfuscate(s3_encrypt_key)}")

        # Confirm with the user that everything looks okay.
        if confirm and not yes_or_no("Confirm the above. Continue with setup?"):
            exit_with_no_action()

        # Confirmed. Proceed with the actual setup steps.
        setup_and_action_state.note_action_start()

        # Create the custom directory itself (already checked it does not yet exist).
        PRINT(f"Creating directory: {custom_dir}")
        os.makedirs(custom_dir)

        # Create the config.json file from the template and the inputs.
        write_config_json_file(custom_dir, {
            ConfigTemplateVars.ACCOUNT_NUMBER: account_number,
            ConfigTemplateVars.DEPLOYING_IAM_USER: deploying_iam_user,
            ConfigTemplateVars.IDENTITY: identity,
            ConfigTemplateVars.S3_BUCKET_ORG: s3_bucket_org,
            ConfigTemplateVars.ENCODED_ENV_NAME: aws_credentials_name
        })

        # Create the secrets.json file from the template and the inputs.
        write_secrets_json_file(custom_dir, {
            SecretsTemplateVars.AUTH0_CLIENT: auth0_client,
            SecretsTemplateVars.AUTH0_SECRET: auth0_secret,
            SecretsTemplateVars.RECAPTCHA_KEY: recaptcha_key,
            SecretsTemplateVars.RECAPTCHA_SECRET: recaptcha_secret
        })

        # Create the symlink from custom/aws_creds to ~/.aws_test.<aws-credentials-name>
        custom_aws_creds_dir = InfraDirectories.get_custom_aws_creds_dir(custom_dir)
        PRINT(f"Creating symlink: {custom_aws_creds_dir}@ -> {aws_credentials_dir} ")
        os.symlink(aws_credentials_dir, custom_aws_creds_dir)

        # Create the S3 encrypt key file (with mode 400).
        # We will NOT overwrite this if it already exists.
        write_s3_encrypt_key_file(custom_dir, s3_encrypt_key)

        # Done. Summarize.
        PRINT("Here is your new local custom config directory:")
        print_directory_tree(custom_dir)


def main(override_argv: Optional[list] = None):
    """
    The main function and args parser for this CLI script.
    Calls into init_custom_dir to do the real work.
    """

    argp = argparse.ArgumentParser()
    argp.add_argument("--account", "-a", dest="account_number", type=str, required=False,
                      help="Your AWS account number")
    argp.add_argument("--auth0client", "-ac", dest="auth0_client", type=str, required=False,
                      help="Your Auth0 client identifier (required)")
    argp.add_argument("--auth0secret", "-as", dest="auth0_secret", type=str, required=False,
                      help="Your Auth0 secret (required)")
    argp.add_argument("--awsdir", "-d", dest="aws_dir", type=str, required=False, default=InfraDirectories.AWS_DIR,
                      help=f"Alternate directory to default: {InfraDirectories.AWS_DIR}")
    argp.add_argument("--awscredentials", "-c", dest="aws_credentials_name", type=str, required=True,
                      help=f"The name of your AWS credentials,"
                           f"e.g. <aws-credentials-name> from {InfraDirectories.AWS_DIR}.<aws-credentials-name>")
    argp.add_argument("--debug", dest="debug", action="store_true", required=False,
                      help="Turn on debugging for this script")
    argp.add_argument("--identity", "-i", dest="identity", type=str, required=False,
                      help="The global application configuration secrets name (generated by default)")
    argp.add_argument("--no-confirm", dest="confirm", action="store_false", required=False,
                      help="Behave as if all confirmation questions were answered yes.")
    argp.add_argument("--out", "-o", dest="custom_dir", type=str, required=False, default=InfraDirectories.CUSTOM_DIR,
                      help=f"Alternate directory to default: {InfraDirectories.CUSTOM_DIR}")
    argp.add_argument("--recaptchakey", "-rk", dest="recaptcha_key", type=str, required=False,
                      help="Your reCAPTCHA key")
    argp.add_argument("--recaptchasecret", "-rs", dest="recaptcha_secret", type=str, required=False,
                      help="Your reCAPTCHA secret")
    argp.add_argument("--s3org", "-n", dest="s3_bucket_org", type=str, required=False,
                      help="Your S3 bucket organization name")
    argp.add_argument("--username", "-u", dest="deploying_iam_user", type=str, required=False,
                      help="Your deploying IAM username")
    args = argp.parse_args(override_argv)

    init_custom_dir(args.aws_dir, args.aws_credentials_name, args.custom_dir, args.account_number,
                    args.deploying_iam_user, args.identity, args.s3_bucket_org, args.auth0_client, args.auth0_secret,
                    args.recaptcha_key, args.recaptcha_secret, args.confirm, args.debug)


if __name__ == "__main__":
    main()
