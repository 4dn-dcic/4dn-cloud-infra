# IN PROGRESS / dmichaels / 2022-06-04
#
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
# --recaptchakey re-captcha-key
#   Use this to specify the 'reCaptchakey' for the secrets.json file.
#
# --recaptchasecret re-captcha-secret
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
#     - os.path.isdir
#     - os.path.isfile
#     - os.path.islink
#     - os.path.join
#     - os.readlink
#     - os.symlink
#   - shell via:
#     - subprocess.check_output (to execute test_cred.sh)

import argparse
import io
import os
import signal
import stat

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
    Directories,
    EnvVars,
    Files,
    SecretsTemplateVars
)


def get_fallback_account_number(env_dir: str) -> str:
    """
    Obtains/returns the account_number value by executing the test_creds.sh
    file for the chosen environment (in a sub-shell) and grabbing the value
    of the ACCOUNT_NUMBER environment value which is likely to be set there.
    :param env_dir: The AWS envronment directory path.
    """
    test_creds_script_file = Files.get_test_creds_script_file(env_dir)
    return read_env_variable_from_subshell(test_creds_script_file, EnvVars.ACCOUNT_NUMBER)


def get_fallback_deploying_iam_user() -> str:
    """
    Obtains/returns the deploying_iam_user value
    simply from the USER environment variable.
    """
    return os.getlogin()


def get_fallback_identity(env_name: str) -> str:
    """
    Obtains/returns the 'identity', i.e. the global application configuration secret name using
    the same code that 4dn-cloud-infra code does (see C4Datastore.application_configuration_secret).
    :param env_name: The AWS environment name.
    """
    try:
        from ...names import Names
        identity_value = Names.application_configuration_secret(env_name)
    except (Exception,) as _:
        identity_value = None
    return identity_value


def main():

    signal.signal(signal.SIGINT, lambda *_: exit_with_no_action("\nCTRL-C"))

    envinfo = AwsEnvInfo(Directories.AWS_DIR)

    # Setup/parse arguments.

    argp = argparse.ArgumentParser()
    argp.add_argument("--env", dest="env_name", type=str, required=True,
                      help=f"The name of your AWS credentials environment, e.g. ENV_NAME from {envinfo.dir}.ENV_NAME")
    argp.add_argument("--awsdir", dest="aws_dir", type=str, required=False, default=Directories.AWS_DIR,
                      help=f"Alternate directory to default: {envinfo.dir}")
    argp.add_argument("--out", dest="custom_dir", type=str, required=False, default=Directories.CUSTOM_DIR,
                      help=f"Alternate directory to default: {Directories.CUSTOM_DIR}")
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
    argp.add_argument("--recaptchakey", dest="re_captcha_key", type=str, required=False,
                      help="Your CAPTCHA key")
    argp.add_argument("--recaptchasecret", dest="re_captcha_secret", type=str, required=False,
                      help="Your CAPTCHA secret")
    argp.add_argument("--debug", dest="debug", action="store_true", required=False,
                      help="Turn on debugging for this script")
    argp.add_argument("--yes", dest="yes", action="store_true", required=False,
                      help="Answer yes for confirmation prompts for this script")
    args = argp.parse_args()

    if args.debug:
        print(f"DEBUG: Current directory: {os.getcwd()}")
        print(f"DEBUG: Current username: {os.environ.get('USER')}")
        print(f"DEBUG: This script directory: {Directories.THIS_SCRIPT_DIR}")

    # Since we allow the base ~/.aws_test to be change via --awsdir
    # we best check that it is not passed as empty.

    args.aws_dir = args.aws_dir.strip()
    if not args.aws_dir:
        exit_with_no_action(f"An ~/.aws directory must be specified; default is: {Directories.AWS_DIR}")

    # Get basic AWS credentials environment info.

    envinfo = AwsEnvInfo(Directories.AWS_DIR)
    current_env = envinfo.current_env
    available_envs = envinfo.available_envs

    if args.debug:
        print(f"DEBUG: AWS directory: {envinfo.dir}")
        print(f"DEBUG: AWS environments: {envinfo.available_envs}")
        print(f"DEBUG: AWS current environment: {envinfo.current_env}")

    # Make sure the AWS environment name given is good.
    # Required but just in case not set anyways, check current
    # environment, if set, and ask them if they want to use that.
    # But don't do this interactive thing if --yes option given,
    # rather just error out on the text if statement after this below.

    args.env_name = args.env_name.strip()
    if not args.env_name and not args.yes:
        if not current_env:
            exit_with_no_action("No environment specified. Use the --env option to specify this.")
        else:
            args.env_name = current_env
            print(f"No environment specified. Use the --env option to specify this.")
            print(f"Though it looks like your current environment is: {current_env}")
            if not confirm_with_user(f"Do you want to use this ({current_env})?"):
                exit_with_no_action()

    # Make sure the environment specified
    # actually exists as a ~/.aws_test.{ENV_NAME} directory.

    if not args.env_name or args.env_name not in available_envs:
        print(f"No environment for this name exists: {args.env_name}")
        if available_envs:
            print("Available environments:")
            for available_env in sorted(available_envs):
                print(f"- {available_env} ({envinfo.get_dir(available_env)})")
            exit_with_no_action("Choose one of the above environment using the --env option.")
        else:
            exit_with_no_action(
                f"No environments found at all.\n"
                f"You need to have at least one {envinfo.dir}.{{ENV_NAME}} directory setup.")

    env_dir = envinfo.get_dir(args.env_name)
    print(f"Setting up 4dn-cloud-infra local custom config directory for environment: {args.env_name}")
    print(f"Your AWS credentials directory: {env_dir}")

    # Determine the custom directory; make sure it doesn't already exist.

    args.custom_dir = args.custom_dir.strip()
    if not args.custom_dir:
        exit_with_no_action("You must specify a custom output directory using the --out option.")

    args.custom_dir = os.path.abspath(args.custom_dir)
    if os.path.exists(args.custom_dir):
        exit_with_no_action(
            f"A custom {'directory' if os.path.isdir(args.custom_dir) else 'file'} already exists: {args.custom_dir}")

    print(f"Using custom directory: {args.custom_dir}")

    # Check/gather all the inputs.

    if not args.account_number:
        if args.debug:
            print(f"DEBUG: Trying to get account number from: {Files.get_test_creds_script_file(env_dir)}")
        args.account_number = get_fallback_account_number(env_dir)
        if not args.account_number:
            args.account_number = input("Or enter your account number: ").strip()
            if not args.account_number:
                exit_with_no_action(f"You must specify an account number. Use the --account option.")
    print(f"Using account number: {args.account_number}")

    if not args.deploying_iam_user:
        args.deploying_iam_user = get_fallback_deploying_iam_user()
        if not args.deploying_iam_user:
            args.deploying_iam_user = input("Or enter your deploying IAM username: ").strip()
            if not args.deploying_iam_user:
                exit_with_no_action(f"You must specify a deploying IAM username. Use the --username option.")
    print(f"Using deploying IAM username: {args.deploying_iam_user}")

    # TODO
    # Display better name than 'identity' for this ... GAC name?

    if not args.identity:
        args.identity = get_fallback_identity(args.env_name)
        if not args.identity:
            args.identity = input("Or enter your global application configuration secret name: ").strip()
            if not args.identity:
                exit_with_no_action(
                    f"You must specify a global application configuration secret name. Use the --identity option.")
    print(f"Using identity: {args.identity}")

    if not args.s3_bucket_org:
        args.s3_bucket_org = input("Or enter your S3 bucket organization name: ").strip()
        if not args.s3_bucket_org:
            exit_with_no_action(f"You must specify an S3 bucket organization. Use the --s3org option.")
    print(f"Using S3 bucket organization name: {args.s3_bucket_org}")

    if not args.auth0_client:
        print("You must specify a Auth0 client ID using the --auth0client option.")
        args.auth0_client = input("Or enter your Auth0 client ID: ").strip()
        if not args.auth0_client:
            exit_with_no_action(f"You must specify an Auth0 client. Use the --auth0client option.")
    print(f"Using Auth0 client: {args.auth0_client}")

    if not args.auth0_secret:
        print("You must specify a Auth0 secret using the --auth0secret option.")
        args.auth0_secret = input("Or enter your Auth0 secret ID: ").strip()
        if not args.auth0_secret:
            exit_with_no_action(f"You must specify an Auth0 secret. Use the --auth0secret option.")
        print(f"Using Auth0 secret: {args.auth0_secret}")
    else:
        print(f"Using Auth0 secret: {obfuscate(args.auth0_secret)}")

    if args.re_captcha_key:
        print(f"Using reCaptchaKey: {args.re_captcha_key}")
    if args.re_captcha_secret:
        print(f"Using reCaptchaSecret: {obfuscate(args.re_captcha_secret)}")

    # Generate S3 encryption key.
    # Though we will NOT overwrite s3_encrypt_key.txt if it already exists, below.

    s3_encrypt_key = generate_s3_encrypt_key()
    print(f"Generating S3 encryption key: {obfuscate(s3_encrypt_key)}")

    # Confirm with the user the everything looks okay.

    if not args.yes and not confirm_with_user("Confirm the above. Continue with setup?"):
        exit_with_no_action()

    # Confirmed.
    # First create the custom directory itself (already checked it does not yet exist).

    print(f"Creating directory: {os.path.abspath(args.custom_dir)}")
    os.makedirs(args.custom_dir)

    # Create the config.json file from the template and the inputs.
    # TODO: Okay if template file is relative to this script directory?

    config_template_file = Files.get_config_template_file()
    config_file = Files.get_config_file(args.custom_dir)

    if args.debug:
        print(f"DEBUG: Config template file: {config_template_file}")
    if not os.path.isfile(config_template_file):
        exit_with_no_action(f"ERROR: Cannot find config template file! {config_template_file}")

    print(f"Creating config file: {os.path.abspath(config_file)}")
    expand_json_template_file(config_template_file, config_file, {
        ConfigTemplateVars.ACCOUNT_NUMBER: args.account_number,
        ConfigTemplateVars.DEPLOYING_IAM_USER: args.deploying_iam_user,
        ConfigTemplateVars.IDENTITY: args.identity,
        ConfigTemplateVars.S3_BUCKET_ORG: args.s3_bucket_org,
        ConfigTemplateVars.ENCODED_ENV_NAME: args.env_name
    })

    # Create the secrets.json file from the template and the inputs.
    # TODO: template file relative to this script directory?

    secrets_template_file = Files.get_secrets_template_file()
    secrets_file = Files.get_secrets_file(args.custom_dir)

    if args.debug:
        print(f"DEBUG: Secrets template file: {secrets_template_file}")
    if not os.path.isfile(secrets_template_file):
        exit_with_no_action(f"ERROR: Cannot find secrets template file! {secrets_template_file}")

    print(f"Creating secrets file: {secrets_file}")
    expand_json_template_file(secrets_template_file, secrets_file, {
        SecretsTemplateVars.AUTH0_CLIENT: args.auth0_client,
        SecretsTemplateVars.AUTH0_SECRET: args.auth0_secret,
        SecretsTemplateVars.RE_CAPTCHA_KEY: args.re_captcha_key,
        SecretsTemplateVars.RE_CAPTCHA_SECRET: args.re_captcha_secret
    })

    # Create the symlink from custom/aws_creds to ~/.aws_test.ENV_NAME.

    custom_aws_creds_dir = Directories.get_custom_aws_creds_dir(args.custom_dir)
    print(f"Creating symlink: {custom_aws_creds_dir} -> {env_dir} ")
    os.symlink(env_dir, custom_aws_creds_dir)

    # Create the S3 encrypt key file (with mode 400).
    # We will NOT overwrite this if it already exists.

    s3_encrypt_key_file = Files.get_s3_encrypt_key_file(args.custom_dir)
    if os.path.exists(s3_encrypt_key_file):
        print(f"S3 encrypt file already exists: {s3_encrypt_key_file}")
        print("Will NOT overwrite this file! Newly generated S3 encryption key not used.")
    else:
        print(f"Creating S3 encrypt file: {s3_encrypt_key_file}")
        with io.open(s3_encrypt_key_file, "w") as s3_encrypt_key_f:
            s3_encrypt_key_f.write(s3_encrypt_key)
            s3_encrypt_key_f.write("\n")
        os.chmod(s3_encrypt_key_file, stat.S_IRUSR)

    # Done. Summarize.

    print("Here is your new local custom config directory:")
    print_directory_tree(args.custom_dir)


if __name__ == "__main__":
    main()
