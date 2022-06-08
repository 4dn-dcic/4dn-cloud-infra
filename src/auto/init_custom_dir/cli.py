# Script to setup the local custom config directory for the 4dn-cloud-infra repo.
# For example like this:
#
#  ─ custom/
#    ├── config.json
#    ├── secrets.json
#    └── aws_creds@ ─> ~/.aws_test.cgap-supertest/
#        ├── credentials
#        ├── test_creds.sh
#        └── s3_encrypt_key.txt
#
# The credentials and test_creds.sh files ared assumed to already exist;
# the former is not used here; the latter actually is used here but only
# to get a default/fallback value for the account_number if not specified.
#
# The config.json and secrets.json files are created from existing template
# files and inputs from the user to this script.
#
# Command-line options:
#
# --env env-name
#   The ENV_NAME corresponding to an existing ~/.aws_test.{ENV_NAME} directory.
#   Required.
#
# --awsdir your-aws-directory
#   Use this to change the default AWS base directory from the default: ~/.aws_test
#
# --out your-custom-directory
#   Use this to change the default custom directory: custom
#
# --account your-aws-account-number
#   Use this to specify the (required) 'account_number' for the config.json file.
#   If not specifed we try to get it from 'ACCOUNT_NUMBER' in test_cred.sh
#   in the specified AWS directory.
#
# --username username
#   Use this to specify the (required) 'deploying_iam_user' for the config.json file.
#   If not specifed we try to get it from the os.getlogin() environment variable.
#
# --identity gac-name
#   Use this to specify the (required) 'identity' for the config.json file,
#   e.g. C4DatastoreCgapSupertestApplicationConfiguration.
#   If not specified we try to get it from the application_configuration_secret
#   function on stacks.alpha_stacks.create_c4_alpha_stack.
#
# --s3org s3-bucket-org
#   Use this to specify the (required) 's3.bucket.org' for the config.json file.
#   Required.
#
# --auth0client auth0-client
#   Use this to specify the (required) 'Auth0Client' for the secrets.json file.
#   Required.
#
# --auth0secret auth0-secret
#   Use this to specify the (required) 'Auth0Secret' for the secrets.json file.
#   Required.
#
# --captchakey captcha-key
#   Use this to specify the 'reCaptchakey' for the secrets.json file.
#
# --captchasecret captcha-secret
#   Use this to specify the 'reCaptchakey' for the secrets.json file.
#
# --debug
#   Use this to turn on debugging output.
#
# --yes
#   Use this to answer yes to any confirmation prompts.
#   Does not guarantee no prompts if insufficient inputs given.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - glob.glob
#     - io.open
#     - os.chmod
#     - os.environ.get
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
import signal
import stat
import sys

from dcicutils.misc_utils import PRINT
from .awsenvinfo import AwsEnvInfo
from .utils import (
    confirm_with_user,
    exit_with_no_action,
    expand_json_template_file,
    generate_s3_encrypt_key,
    obfuscate,
    print_directory_tree,
    read_env_variable_from_subshell
)
from .defs import (
    ConfigTemplateVars,
    InfraDirectories,
    EnvVars,
    InfraFiles,
    SecretsTemplateVars
)
from ...names import Names


def get_fallback_account_number(env_dir: str) -> str:
    """
    Obtains/returns fallback account_number value by executing the test_creds.sh
    file for the chosen environment (in a sub-shell) and grabbing the value
    of the ACCOUNT_NUMBER environment value which is likely to be set there.

    :param env_dir: The AWS envronment directory path.
    :return: The account number from test_creds.sh if found otherwise None.
    """
    test_creds_script_file = InfraFiles.get_test_creds_script_file(env_dir)
    return read_env_variable_from_subshell(test_creds_script_file, EnvVars.ACCOUNT_NUMBER)


def get_fallback_deploying_iam_user() -> str:
    """
    Obtains/returns fallback deploying_iam_user value, simply from the OS environment.

    :return: Username as found by os.getlogin().
    """
    return os.getlogin()


def get_fallback_identity(env_name: str) -> str:
    """
    Obtains/returns the 'identity', i.e. the global application configuration name using
    the same code that 4dn-cloud-infra code does (see C4Datastore.application_configuration_secret).
    Had to do some refactoring to get this working (see names.py).

    :param env_name: AWS environment name (e.g. cgap-supertest).
    :return: The identity as gotten from the main 4dn-cloud-infra code.
    """
    try:
        identity_value = Names.application_configuration_secret(env_name)
    except (Exception,) as _:
        identity_value = None
    return identity_value


def parse_args(argv: list = None):
    """
    The main args parser for this CLI script.
    :return: The args as returned by argparse.ArgumentParser.parse_args().
    """
    argp = argparse.ArgumentParser()
    argp.add_argument("--env", dest="env_name", type=str, required=True,
                      help=f"The name of your AWS environment,"
                           f"e.g. ENV_NAME from {InfraDirectories.AWS_DIR}.ENV_NAME")
    argp.add_argument("--awsdir", dest="aws_dir", type=str, required=False, default=InfraDirectories.AWS_DIR,
                      help=f"Alternate directory to default: {InfraDirectories.AWS_DIR}")
    argp.add_argument("--out", dest="custom_dir", type=str, required=False, default=InfraDirectories.CUSTOM_DIR,
                      help=f"Alternate directory to default: {InfraDirectories.CUSTOM_DIR}")
    argp.add_argument("--account", dest="account_number", type=str, required=False,
                      help="Your AWS account number")
    argp.add_argument("--username", dest="deploying_iam_user", type=str, required=False,
                      help="Your deploying IAM username")
    argp.add_argument("--identity", dest="identity", type=str, required=False,
                      help="The global application configuration secrets name (generated by default)")
    argp.add_argument("--s3org", dest="s3_bucket_org", type=str, required=False,
                      help="Your S3 bucket organization name")
    argp.add_argument("--auth0client", dest="auth0_client", type=str, required=False,
                      help="Your Auth0 client identifier (required)")
    argp.add_argument("--auth0secret", dest="auth0_secret", type=str, required=False,
                      help="Your Auth0 secret (required)")
    argp.add_argument("--captchakey", dest="captcha_key", type=str, required=False,
                      help="Your CAPTCHA key")
    argp.add_argument("--captchasecret", dest="captcha_secret", type=str, required=False,
                      help="Your CAPTCHA secret")
    argp.add_argument("--debug", dest="debug", action="store_true", required=False,
                      help="Turn on debugging for this script")
    argp.add_argument("--yes", dest="yes", action="store_true", required=False,
                      help="Answer yes for confirmation prompts for this script")
    return argp.parse_args(argv)


def check_env(aws_dir: str, env_name: str, yes: bool = False, debug: bool = False) -> (str, str):
    """
    Checks the given AWS directory and AWS environment name and returns
    the AWS environment name and full path to the associated AWS directory.
    May prompt for input if not set, and may exit on error.

    :param aws_dir: Specified AWS base directory (default: ~/.aws_test from InfraDirectories.AWS_DIR).
    :param env_name: Specified AWS environment name.
    :param yes: True to automatically answer yes to confirmation prompts.
    :param debug: True for debugging output.
    :return: Tuple with AWS environment name and full path to associated AWS directory.
    """
    # Since we allow the base ~/.aws_test to be changed
    # via --awsdir we best check that it is not passed as empty.
    # Note the default aws_dir comes from InfraDirectories.AWS_DIR in parse_args.

    aws_dir = aws_dir.strip()
    if not aws_dir:
        exit_with_no_action(f"An ~/.aws directory must be specified; default is: {InfraDirectories.AWS_DIR}")

    # Get basic AWS environment info.

    envinfo = None
    try:
        envinfo = AwsEnvInfo(aws_dir)
    except (Exception,) as e:
        exit_with_no_action(str(e))

    if debug:
        PRINT(f"DEBUG: AWS base directory: {envinfo.dir}")
        PRINT(f"DEBUG: AWS environments: {envinfo.available_envs}")
        PRINT(f"DEBUG: AWS current environment: {envinfo.current_env}")

    # Make sure the AWS environment name given is good.
    # Required but just in case not set anyways, check current
    # environment, if set, and ask them if they want to use that.
    # But don't do this interactive thing if --yes option given,
    # rather just error out on the text if statement after this below.

    env_name = env_name.strip()
    if not env_name and not yes:
        if not envinfo.current_env:
            exit_with_no_action("No environment specified. Use the --env option to specify this.")
        else:
            env_name = envinfo.current_env
            PRINT(f"No environment specified. Use the --env option to specify this.")
            PRINT(f"Though it looks like your current environment is: {envinfo.current_env}")
            if not confirm_with_user(f"Do you want to use this ({envinfo.current_env})?"):
                exit_with_no_action()

    # Make sure the environment specified
    # actually exists as a ~/.aws_test.{ENV_NAME} directory.

    if not env_name or env_name not in envinfo.available_envs:
        PRINT(f"No environment for this name exists: {env_name}")
        if envinfo.available_envs:
            PRINT("Available environments:")
            for available_env in sorted(envinfo.available_envs):
                PRINT(f"* {available_env} -> {envinfo.get_dir(available_env)}")
            exit_with_no_action("Choose one of the above environment using the --env option.")
        else:
            exit_with_no_action(
                f"No environments found at all.\n"
                f"You need to have at least one {envinfo.dir}.{{ENV_NAME}} directory setup.")

    env_dir = envinfo.get_dir(env_name)

    PRINT(f"Setting up 4dn-cloud-infra local custom config directory for environment: {env_name}")
    PRINT(f"Your AWS environment directory: {env_dir}")

    return env_name, env_dir


def check_custom_dir(custom_dir: str) -> str:
    """
    Checks the given custom directory and returns its full path.
    May prompt for input if not set, and may exit on error.

    :param custom_dir: Specified custom directory.
    :return: Full path to custom directory.
    """
    custom_dir = custom_dir.strip()
    if not custom_dir:
        exit_with_no_action("You must specify a custom output directory using the --out option.")

    custom_dir = os.path.abspath(os.path.expanduser(custom_dir))
    if os.path.exists(custom_dir):
        exit_with_no_action(
            f"A custom {'directory' if os.path.isdir(custom_dir) else 'file'} already exists: {custom_dir}")

    PRINT(f"Using custom directory: {custom_dir}")
    return custom_dir


def check_account_number(account_number: str, env_dir: str, debug: bool = False) -> str:
    """
    Checks the given account number (if specified), and returns it if/when set.
    If not specified we try to get it from test_creds.sh.
    May prompt for input if not set, and may exit on error.

    :param account_number: Account number value.
    :param env_dir: Full path to AWS environment directory.
    :param debug: True for debugging output.
    :return: Account number value.
    """
    if not account_number:
        if debug:
            PRINT(f"DEBUG: Trying to get account number from: {InfraFiles.get_test_creds_script_file(env_dir)}")
        account_number = get_fallback_account_number(env_dir)
        if not account_number:
            account_number = input("Or enter your account number: ").strip()
            if not account_number:
                exit_with_no_action(f"You must specify an account number. Use the --account option.")
    PRINT(f"Using account number: {account_number}")
    return account_number


def check_deploying_iam_user(deploying_iam_user: str) -> str:
    """
    Checks the given deploying IAM username and returns it if/when set.
    May prompt for input if not set, and may exit on error.

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


def check_identity(identity: str, env_name: str) -> str:
    """
    Checks the given identity (i.e. GAC name) and returns it if/when set.
    May prompt for input if not set, and may exit on error.

    :param identity: Identity (i.e. GAC name) value.
    :param env_name: AWS environment name (e.g. cgap-supertest).
    :return: Identity (i.e. GAC name) value.
    """
    if not identity:
        identity = get_fallback_identity(env_name)
        if not identity:
            PRINT("Cannot determine global application configuration name. Use the --identity option.")
            identity = input("Or enter your global application configuration name: ").strip()
            if not identity:
                exit_with_no_action(
                    f"You must specify a global application configuration name. Use the --identity option.")
    PRINT(f"Using global application configuration name: {identity}")
    return identity


def check_s3_bucket_org(s3_bucket_org: str) -> str:
    """
    Checks the given S3 bucket organization name and returns it if/when set.
    May prompt for input if not set, and may exit on error.

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


def check_auth0(auth0_client: str, auth0_secret: str) -> (str, str):
    """
    Checks the given Auth0 client/secret and returns them if/when set.
    May prompt for input if not set, and may exit on error.

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


def check_captcha(captcha_key: str, captcha_secret: str) -> (str, str):
    """
    Checks the given CAPTCHA key/secret and returns them if/when set.
    May prompt for input if not set, and may exit on error.

    :param captcha_key: CAPTCHA key value.
    :param captcha_secret: CAPTCHA secret value.
    :return: Tuple with CAPTCHA key and secret values.
    """
    if captcha_key:
        PRINT(f"Using CAPTCHA key: {captcha_key}")
    if captcha_secret:
        PRINT(f"Using CAPTCHA secret: {obfuscate(captcha_secret)}")
    return captcha_key, captcha_secret


def write_config_json_file(custom_dir: str, substitutions: dict, debug: bool = False) -> None:
    """
    Writes the config.json file in given custom directory based on our template and given substitutions.
    Uses the dcicutils.misc_utils.json_leaf_subst (from utils.expand_json_template_file) for this.
    May exit on error.

    :param custom_dir: Full path to the custom directory.
    :param substitutions: Substitutions to use in template expansion.
    :param debug: True for debugging output.
    """
    config_template_file = InfraFiles.get_config_template_file()
    config_file = InfraFiles.get_config_file(custom_dir)

    if debug:
        PRINT(f"DEBUG: Config template file: {config_template_file}")
    if not os.path.isfile(config_template_file):
        exit_with_no_action(f"ERROR: Cannot find config template file! {config_template_file}")

    PRINT(f"Creating config file: {config_file}")
    expand_json_template_file(config_template_file, config_file, substitutions)


def write_secrets_json_file(custom_dir: str, substitutions: dict, debug: bool = False) -> None:
    """
    Writes the secrets.json file in given custom directory based on our template and given substitutions.
    Uses the dcicutils.misc_utils.json_leaf_subst (from utils.expand_json_template_file) for this.
    May exit on error.

    :param custom_dir: Full path to the custom directory.
    :param substitutions: Substitutions to use in template expansion.
    :param debug: True for debugging output.
    """
    secrets_template_file = InfraFiles.get_secrets_template_file()
    secrets_file = InfraFiles.get_secrets_file(custom_dir)

    if debug:
        PRINT(f"DEBUG: Secrets template file: {secrets_template_file}")
    if not os.path.isfile(secrets_template_file):
        exit_with_no_action(f"ERROR: Cannot find secrets template file! {secrets_template_file}")

    PRINT(f"Creating secrets file: {secrets_file}")
    expand_json_template_file(secrets_template_file, secrets_file, substitutions)


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
        with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_f:
            s3_encrypt_key_f.write(s3_encrypt_key)
            s3_encrypt_key_f.write("\n")
        os.chmod(s3_encrypt_key_file, stat.S_IRUSR)


def main(argv: list = None):

    signal.signal(signal.SIGINT, lambda *_: exit_with_no_action("\nCTRL-C"))

    # Parse arguments.

    args = parse_args(argv)

    if args.debug:
        PRINT(f"DEBUG: Current directory: {os.getcwd()}")
        PRINT(f"DEBUG: Current username: {os.environ.get('USER')}")
        PRINT(f"DEBUG: Script directory: {InfraDirectories.THIS_SCRIPT_DIR}")

    # Check/gather all the inputs.

    env_name, env_dir = check_env(args.aws_dir, args.env_name, args.yes, args.debug)
    custom_dir = check_custom_dir(args.custom_dir)
    account_number = check_account_number(args.account_number, env_dir)
    deploying_iam_user = check_deploying_iam_user(args.deploying_iam_user)
    identity = check_identity(args.identity, env_name)
    s3_bucket_org = check_s3_bucket_org(args.s3_bucket_org)
    auth0_client, auth0_secret = check_auth0(args.auth0_client, args.auth0_secret)
    captcha_key, captcha_secret = check_captcha(args.captcha_key, args.captcha_secret)

    # Generate S3 encryption key.
    # Though we will NOT overwrite s3_encrypt_key.txt if it already exists, below.

    s3_encrypt_key = generate_s3_encrypt_key()
    PRINT(f"Generating S3 encryption key: {obfuscate(s3_encrypt_key)}")

    # Confirm with the user that everything looks okay.

    if not args.yes and not confirm_with_user("Confirm the above. Continue with setup?"):
        exit_with_no_action()

    # Confirmed.
    # First create the custom directory itself (already checked it does not yet exist).

    PRINT(f"Creating directory: {custom_dir}")
    os.makedirs(custom_dir)

    # Create the config.json file from the template and the inputs.

    write_config_json_file(custom_dir, {
        ConfigTemplateVars.ACCOUNT_NUMBER: account_number,
        ConfigTemplateVars.DEPLOYING_IAM_USER: deploying_iam_user,
        ConfigTemplateVars.IDENTITY: identity,
        ConfigTemplateVars.S3_BUCKET_ORG: s3_bucket_org,
        ConfigTemplateVars.ENCODED_ENV_NAME: env_name
    })

    # Create the secrets.json file from the template and the inputs.

    write_secrets_json_file(custom_dir, {
        SecretsTemplateVars.AUTH0_CLIENT: auth0_client,
        SecretsTemplateVars.AUTH0_SECRET: auth0_secret,
        SecretsTemplateVars.RE_CAPTCHA_KEY: captcha_key,
        SecretsTemplateVars.RE_CAPTCHA_SECRET: captcha_secret
    })

    # Create the symlink from custom/aws_creds to ~/.aws_test.{ENV_NAME}.

    custom_aws_creds_dir = InfraDirectories.get_custom_aws_creds_dir(custom_dir)
    PRINT(f"Creating symlink: {custom_aws_creds_dir}@ -> {env_dir} ")
    os.symlink(env_dir, custom_aws_creds_dir)

    # Create the S3 encrypt key file (with mode 400).
    # We will NOT overwrite this if it already exists.

    write_s3_encrypt_key_file(custom_dir, s3_encrypt_key)

    # Done. Summarize.

    PRINT("Here is your new local custom config directory:")
    print_directory_tree(custom_dir)


if __name__ == "__main__":
    main(sys.argv[1:])
