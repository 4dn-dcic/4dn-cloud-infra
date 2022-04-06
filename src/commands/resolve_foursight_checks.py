import argparse
import io
import json
import os

from chalicelib.vars import CHECK_SETUP_FILE as FOURSIGHT_CHECK_TEMPLATE
from dcicutils.misc_utils import full_class_name, json_leaf_subst

from ..constants import Settings


EPILOG = __doc__

DEFAULT_ENVIRONMENT = os.environ.get("ENV_NAME")
if DEFAULT_ENVIRONMENT is None:
    from ..base import ConfigManager  # Allow command without custom dir -drr 04/05/2022
    DEFAULT_ENVIRONMENT = ConfigManager.get_config_setting(Settings.ENV_NAME)

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
