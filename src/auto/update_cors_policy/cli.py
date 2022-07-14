# Script for 4dn-cloud-infra to update KMS key policy for Foursight.

import argparse
import json
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ..utils.args_utils import add_aws_credentials_args, validate_aws_credentials_args
from ..utils.paths import InfraDirectories
from ..utils.misc_utils import (
    exit_with_no_action,
    setup_and_action,
)
from ..utils.validate_utils import (
    validate_and_get_aws_credentials, validate_and_get_aws_credentials_dir,
    validate_and_get_aws_credentials_name, validate_and_get_custom_dir
)


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

    with setup_and_action() as setup_and_action_state:

        # Gather the basic info.
        custom_dir, config_file = validate_and_get_custom_dir(custom_dir)
        aws_credentials_name = validate_and_get_aws_credentials_name(aws_credentials_name, config_file)
        aws_credentials_dir = validate_and_get_aws_credentials_dir(aws_credentials_dir, custom_dir)

        # Print header and basic info.
        PRINT(f"Updating 4dn-cloud-infra CORS policy for S3 bucket(s).")
        PRINT(f"Your custom directory: {custom_dir}")
        PRINT(f"Your custom config file: {config_file}")
        PRINT(f"Your AWS credentials name: {aws_credentials_name}")

        # Validate and print basic AWS credentials info.
        aws, aws_credentials = validate_and_get_aws_credentials(aws_credentials_dir,
                                                                aws_access_key_id,
                                                                aws_secret_access_key,
                                                                aws_region,
                                                                aws_session_token,
                                                                config_file,
                                                                show)

        # Get currently defined CORS rules from AWS for the bucket.
        cors_rules = aws.get_cors_rules(bucket_name)

        if cors_rules is None:
            exit_with_no_action(f"S3 bucket not found: {bucket_name}")

        if debug:
            print(f"DEBUG: Existing CORS rules for the S3 bucket: {bucket_name}")
            print(json.dumps(cors_rules, default=str, indent=2))

        # Enumerate URLs currently assocatied with relevant CORS rule, if any.
        existing_rule_urls = get_relevant_cors_rule(cors_rules)
        if existing_rule_urls:
            print(f"CORS policy rule already exists for this S3 bucket for URLs below: {bucket_name}")
            [print(f"- {existing_rule_url}") for existing_rule_url in existing_rule_urls]

        # Amend the currently defined CORS rules with one for the given URL.
        if not amend_cors_rules(cors_rules, url):
            exit_with_no_action(f"CORS policy already has a policy rule for: {url}")

        # Here we want to update the CORS rule. Summarize before confirmation.
        print(f"S3 bucket for which to update the CORS policy: {bucket_name}")
        print(f"URL for which to update S3 bucket CORS policy: {url}")

        # Confirm the update.
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
    # TODO: Make the --bucket option not required and suggest buckets (the files and wfoutput ones).
    argp.add_argument("--bucket", required=True,
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
