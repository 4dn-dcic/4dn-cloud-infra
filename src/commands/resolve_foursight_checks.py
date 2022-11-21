import argparse
import io
import json
import os
import sys
from dcicutils.env_utils import EnvUtils
from dcicutils.secrets_utils import assumed_identity
from foursight_core.check_utils import CheckHandler


# Importing both chalicelib_cgap and chalicelib_fourfront from (now) separate packages;
# choose which one is the source via the (new) --app argument. dmichaels/2022-10-31.
# from .chalicelib.package import PackageDeploy as PackageDeploy_from_app
from chalicelib_fourfront.vars import CHECK_SETUP_FILE as FOURSIGHT_FOURFRONT_CHECK_TEMPLATE
#from chalicelib_cgap.vars import CHECK_SETUP_FILE as FOURSIGHT_CGAP_CHECK_TEMPLATE
FOURSIGHT_CGAP_CHECK_TEMPLATE = ''
from dcicutils.misc_utils import full_class_name

from src.constants import Settings
from src.exceptions import CLIException


EPILOG = __doc__

DEFAULT_ENVIRONMENT = os.environ.get("ENV_NAME")
if DEFAULT_ENVIRONMENT is None:
    try:
        from src.base import ConfigManager  # Import will fail without custom dir
        DEFAULT_ENVIRONMENT = ConfigManager.get_config_setting(Settings.ENV_NAME)
    except CLIException:
        raise RuntimeError(
            "Could not determine environment name. Please set environmental variable"
            " 'ENV_NAME' or configure the custom directory."
        )
DEFAULT_TARGET_FILE = "vendor/check_setup.json"
#ENV_NAME_MARKER = "<env-name>"


def resolve_foursight_checks(env_name=None, template_file=None, target_file=None, app_name=None):
    """
    Substitutes the given env_name for the JSON string token "<env-name>" in the content of the template file,
    writing the result as the target file.
    """
    # This app_name is a new (November 2022) --app command-line argument
    # to help distinguish between foursight-cgap and foursight-fourfront.
    if app_name in ["foursight-fourfront", "fourfront"]:
        foursight_check_template = FOURSIGHT_FOURFRONT_CHECK_TEMPLATE
    else:
        foursight_check_template = FOURSIGHT_CGAP_CHECK_TEMPLATE
    env_name = env_name or DEFAULT_ENVIRONMENT
    template_file = template_file or foursight_check_template
    target_file = target_file or DEFAULT_TARGET_FILE
    target_file = os.path.abspath(target_file)
    print(f"Source template file: {template_file}")
    print(f"Environment name: {env_name}")
    print(f"Target file: {template_file}")
    with io.open(template_file, 'r') as input_fp:
        template_value = json.load(input_fp)
    # This expansion of the <env-name> placeholders within the check_seutp.json may
    # now be done here, but it is also done dynamically at runtime in foursight_core.
    # dmichaels/2022-11-01.
    # checks = json_leaf_subst(template_value, {ENV_NAME_MARKER: env_name})
    checks = CheckHandler.expand_check_setup(template_value, env_name)
    with io.open(target_file, 'w') as output_fp:
        json.dump(checks, output_fp, indent=2)
        output_fp.write('\n')  # Write a trailing newline
        print(f"Target file written: {target_file}.")


# def json_subst_all(exp, substitutions):  # This might want to move to dcicutils.misc_utils later
#     """
#     Given an expression and some substitutions, substitutes all occurrences of the given
#     """
#     def do_subst(e):
#         return json_subst_all(e, substitutions)
#     if isinstance(exp, dict):
#         return {do_subst(k): do_subst(v) for k, v in exp.items()}
#     elif isinstance(exp, list):
#         return [do_subst(e) for e in exp]
#     elif exp in substitutions:  # Something atomic like a string or number
#         return substitutions[exp]
#     return exp


def main(simulated_args=None):

    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Resolve the foursight check_setup.json file based on template in check_json.template.json",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env_name", default=None,
                        help=f"name of environment to configure (default {DEFAULT_ENVIRONMENT})")
    parser.add_argument("--template_file", default=None,
                        help=f"template path to use for testing instead of {FOURSIGHT_CGAP_CHECK_TEMPLATE} or {FOURSIGHT_FOURFRONT_CHECK_TEMPLATE}")
    parser.add_argument("--target_file", default=None,
                        help=f"target path to use for testing instead of {DEFAULT_TARGET_FILE}")
    parser.add_argument("--app", type=str, default=None, required=True,
                        help=f"Choose Foursight-CGAP or Foursight-Fourfront")
    args = parser.parse_args(args=simulated_args)

    # New (November 2022) --app command-line argument to help
    # distinguish between foursight-cgap and foursight-fourfront.
    if args.app not in ["foursight-cgap", "cgap", "foursight-fourfront", "fourfront"]:
        print("The --app argument must specify one of: cgap, fourfront")
        exit(1)

    try:
        resolve_foursight_checks(env_name=args.env_name, template_file=args.template_file, target_file=args.target_file, app_name=args.app)
    except Exception as e:
        print(f"{full_class_name(e)}: {str(e)}")
        exit(1)
