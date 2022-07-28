# Script for 4dn-cloud-infra to update KMS key policy for Foursight.

import argparse
import json
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ...names import Names
from ..utils.aws import Aws
from ..utils.args_utils import add_aws_credentials_args, validate_aws_credentials_args
from ..utils.paths import InfraDirectories
from ..utils.misc_utils import (
    exit_with_no_action,
    setup_and_action,
)
from ..utils.validate_utils import (
    validate_and_get_aws_credentials,
)


def get_app_files_bucket_name(aws: Aws, aws_credentials_name: str) -> str:
    """
    Returns the S3 bucket name for the application files.
    """
    stack_name = Names.datastore_stack_name(aws_credentials_name)
    stack_output_key_name = Names.datastore_stack_output_app_files_bucket_key(aws_credentials_name)
    return aws.get_stack_output_value(stack_name, stack_output_key_name)


def get_app_wfout_bucket_name(aws: Aws, aws_credentials_name: str) -> str:
    """
    Returns the S3 bucket name for the application wfoutput.
    """
    stack_name = Names.datastore_stack_name(aws_credentials_name)
    stack_output_key_name = Names.datastore_stack_output_app_wfout_bucket_key(aws_credentials_name)
    return aws.get_stack_output_value(stack_name, stack_output_key_name)


def amend_cors_rules(cors_rules: list, url: str) -> True:
    """
    Amends the given CORS rules with a relevant rule for the given URL,
    and return True if the CORS rules were updated; if there is already
    a relevant rule for the given URL, then do nothing and return False.
    For our purposes a "relevant" CORS rule is one with a "GET" method and a "*" header.

    :param cors_rules: List of CORS rules.
    :param url: URL for which to add a relevant CORS rule.
    :return: True if the given CORS rules were updated, otherwise False.
    """
    for cors_rule in cors_rules:
        allowed_methods = cors_rule.get("AllowedMethods")
        if "GET" in allowed_methods:
            allowed_headers = cors_rule.get("AllowedHeaders")
            if "*" in allowed_headers:
                # Here, we have a relevant CORS rule.
                allowed_origins = cors_rule.get("AllowedOrigins")
                if not allowed_origins:
                    # Here, we have a relevant CORS rule with no allowed origins (URLs);
                    # it appears this cannot actually happen but just in case.
                    cors_rule["AllowedOrigins"] = []
                elif url in allowed_origins:
                    # Here, we have a relevant CORS rule which already has the given URL;
                    # return False to indicate no AWS changes necessary.
                    return False
                # Add the given URL to the list of allowed origins (URLs);
                # and return True indicating AWS changes are necessary.
                cors_rule["AllowedOrigins"].append(url)
                return True
    # Here, we do not have a relevant CORS rule at all; add it for the given URL;
    # and return True indicating AWS changes are necessary.
    new_cors_rule = {
        "AllowedMethods": ["GET"],
        "AllowedHeaders": ["*"],
        "AllowedOrigins": [url]
    }
    cors_rules.append(new_cors_rule)
    return True


def get_relevant_cors_rule(cors_rules: list) -> Optional[list]:
    """
    Returns the list of URLs associated with the relevant rule
    in the given list of CORS rules, or None of no relevant rule found.

    :param: List of CORS rules.
    :return: List of URLs associated with the found relevant CORS rule, or None.
    """
    for cors_rule in cors_rules:
        allowed_methods = cors_rule.get("AllowedMethods")
        if "GET" in allowed_methods:
            allowed_headers = cors_rule.get("AllowedHeaders")
            if "*" in allowed_headers:
                return cors_rule.get("AllowedOrigins")
    return None


def print_suggested_buckets(aws: Aws, aws_credentials_name: str) -> None:

    def print_suggested_bucket(bucket_name: str) -> None:
        print(f"- {bucket_name}")
        cors_rules = aws.get_cors_rules(bucket_name)
        existing_rule_urls = get_relevant_cors_rule(cors_rules)
        if existing_rule_urls:
            [print(f"  - {existing_rule_url}") for existing_rule_url in existing_rule_urls]

    print(f"Here are the suggested buckets (with any relevant CORS rule URLs):")
    app_files_bucket_name = get_app_files_bucket_name(aws, aws_credentials_name)
    print_suggested_bucket(app_files_bucket_name)
    app_wfout_bucket_name = get_app_wfout_bucket_name(aws, aws_credentials_name)
    print_suggested_bucket(app_wfout_bucket_name)


def update_cors_policy(
        aws_access_key_id: str,
        aws_credentials_dir: str,
        aws_credentials_name: str,
        aws_region: str,
        aws_secret_access_key: str,
        aws_session_token,
        bucket_name: str,
        custom_dir: str,
        debug: bool,
        show: bool,
        url: str) -> None:
    """
    Main logical entry point for this script.
    Gathers, prints, confirms, and updates the CORS policy for the given S3 bucket.
    """
    PRINT(f"Updating 4dn-cloud-infra CORS policy rules for S3 bucket.")

    with setup_and_action() as setup_and_action_state:

        # Validate/get and print basic AWS credentials info.
        aws = validate_and_get_aws_credentials(aws_credentials_name,
                                               aws_credentials_dir,
                                               custom_dir,
                                               aws_access_key_id,
                                               aws_secret_access_key,
                                               aws_region,
                                               aws_session_token,
                                               show)

        if not bucket_name:
            print(f"AWS S3 bucket name required. Use the --bucket option.")
            print_suggested_buckets(aws, aws.credentials_name)
            exit_with_no_action()

        print(f"S3 bucket for which to update the CORS policy: {bucket_name}")
        print(f"URL for which to update S3 bucket CORS policy: {url}")

        # Get currently defined CORS rules from AWS for the bucket.
        cors_rules = aws.get_cors_rules(bucket_name)

        if debug and cors_rules:
            print(f"DEBUG: Existing CORS rules for the S3 bucket: {bucket_name}")
            print(json.dumps(cors_rules, default=str, indent=2))

        if cors_rules is None:
            print(f"S3 bucket not found: {bucket_name}")
            print_suggested_buckets(aws, aws.credentials_name)
            exit_with_no_action()
        elif len(cors_rules) == 0:
            print(f"No CORS policy currently set for this S3 bucket: {bucket_name}")
        else:
            existing_rule_urls = get_relevant_cors_rule(cors_rules)
            if existing_rule_urls:
                print(f"CORS policy rule with below URLs currently exist for given S3 bucket: {bucket_name}")
                [print(f"- {existing_rule_url}") for existing_rule_url in existing_rule_urls]
            else:
                print(f"No relevant CORS policy rule currently set for this S3 bucket: {bucket_name}")

        # Amend the currently defined CORS rules with one for the given URL.
        if not amend_cors_rules(cors_rules, url):
            exit_with_no_action(f"CORS policy already has a policy rule for given URL: {url}")

        # Here we want to update the CORS rule. Confirm.
        yes = yes_or_no("Continue with update?")
        if not yes:
            exit_with_no_action()

        setup_and_action_state.note_action_start()

        # Actually update the CORS rule in AWS for the bucket.
        aws.put_cors_rules(bucket_name, cors_rules)


def main(override_argv: Optional[list] = None) -> None:
    """
    Main entry point for this script. Parses command-line arguments and calls the main logical entry point.

    :param override_argv: Raw command-line arguments for this invocation.
    """
    argp = argparse.ArgumentParser()
    add_aws_credentials_args(argp)
    argp.add_argument("--custom-dir", required=False, default=InfraDirectories.CUSTOM_DIR,
                      help=f"Alternate custom config directory to default: {InfraDirectories.CUSTOM_DIR}.")
    argp.add_argument("--no-confirm", required=False,
                      dest="confirm", action="store_false",
                      help="Behave as if all confirmation questions were answered yes.")
    argp.add_argument("--bucket", required=False,
                      dest="bucket_name",
                      help="S3 encryption key ID.")
    argp.add_argument("--url", required=True,
                      help="URL for which to enable CORS.")
    argp.add_argument("--show", action="store_true", required=False)
    argp.add_argument("--debug", action="store_true", required=False)
    args = argp.parse_args(override_argv)
    validate_aws_credentials_args(args)

    update_cors_policy(
        args.aws_access_key_id,
        args.aws_credentials_dir,
        args.aws_credentials_name,
        args.aws_region,
        args.aws_secret_access_key,
        args.aws_session_token,
        args.bucket_name,
        args.custom_dir,
        args.debug,
        args.show,
        args.url)


if __name__ == "__main__":
    main()
