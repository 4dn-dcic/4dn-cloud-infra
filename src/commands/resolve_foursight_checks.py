import argparse
import io
import json
import os
import sys


def is_foursight_fourfront():
    def get_identity_from_command_line():
        for i in range(len(sys.argv)):
            if sys.argv[i] == "--foursight-identity":
                if i + 1 < len(sys.argv):
                    return sys.argv[i + 1]
        return None
    identity = os.environ.get("IDENTITY", None)
    if not identity:
        # This seem 100% lame. But need to be able to determine if this is foursight-cgap or foursight-fourfronnt
        # right at startup even before command-line args are parsed (in cli.py) e.g. to do conditional import of
        # chalicelib_cgap.PackageDeploy or chalicelib_fourfront.PackageDeploy in stack.py.
        identity = get_identity_from_command_line()
    with assumed_identity(identity_name=identity):
        EnvUtils.init()
        is_foursight_fourfront = EnvUtils.app_case(if_cgap=False, if_fourfront=True)
        return is_foursight_fourfront

if is_foursight_fourfront():
    from chalicelib_fourfront.vars import CHECK_SETUP_FILE as FOURSIGHT_CHECK_TEMPLATE
else:
    from chalicelib_cgap.vars import CHECK_SETUP_FILE as FOURSIGHT_CHECK_TEMPLATE
from dcicutils.misc_utils import full_class_name, json_leaf_subst

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
ENV_NAME_MARKER = "<env-name>"


def resolve_foursight_checks(env_name=None, template_file=None, target_file=None):
    """
    Substitutes the given env_name for the JSON string token "<env-name>" in the content of the template file,
    writing the result as the target file.
    """
    env_name = env_name or DEFAULT_ENVIRONMENT
    template_file = template_file or FOURSIGHT_CHECK_TEMPLATE
    target_file = target_file or DEFAULT_TARGET_FILE
    with io.open(template_file, 'r') as input_fp:
        template_value = json.load(input_fp)
    checks = json_leaf_subst(template_value, {ENV_NAME_MARKER: env_name})
    with io.open(target_file, 'w') as output_fp:
        json.dump(checks, output_fp, indent=2)
        output_fp.write('\n')  # Write a trailing newline
        print(f"{os.path.abspath(target_file)} written.")


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
                        help=f"template path to use for testing instead of {FOURSIGHT_CHECK_TEMPLATE}")
    parser.add_argument("--target_file", default=None,
                        help=f"target path to use for testing instead of {DEFAULT_TARGET_FILE}")
    args = parser.parse_args(args=simulated_args)

    try:
        resolve_foursight_checks(env_name=args.env_name, template_file=args.template_file, target_file=args.target_file)
    except Exception as e:
        print(f"{full_class_name(e)}: {str(e)}")
        exit(1)
