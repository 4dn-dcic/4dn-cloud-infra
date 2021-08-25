import argparse
import boto3
import subprocess

from dcicutils.misc_utils import find_association, PRINT
from ..base import ConfigManager, ENV_NAME, ECOSYSTEM, camelize, COMMON_STACK_PREFIX_CAMEL_CASE
from ..constants import Settings
from ..parts.ecs import C4ECSApplicationExports


EPILOG = __doc__


REGION = 'us-east-1'  # TODO: make customizable


def hyphenify(x):
    return x.replace("_", "-")


# I didn't use the actual code snippets that were given, but this information was useful:
# https://stackoverflow.com/questions/36560504/how-do-i-find-the-api-endpoint-of-a-lambda-function

def get_foursight_url(*, env_name=ENV_NAME, region=REGION):
    api_gateway = boto3.client('apigateway')
    if region is None:
        region = api_gateway.meta.region_name
    if env_name is None:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
    rest_apis = api_gateway.get_rest_apis()['items']
    foursight_api = find_association(rest_apis, name=lambda x: x.startswith("foursight_"))
    if not foursight_api:
        raise RuntimeError("There is no foursight api at this time.")
    foursight_api_id = foursight_api['id']
    foursight_url = f"https://{foursight_api_id}.execute-api.{region}.amazonaws.com/api/view/{env_name}"
    return foursight_url


def open_foursight_url(*, env_name=ENV_NAME, region=REGION):
    foursight_url = get_foursight_url(region=region, env_name=env_name)
    subprocess.check_output(['open', foursight_url])


def get_portal_url(*, env_name=ENV_NAME):
    result = C4ECSApplicationExports.get_application_url(env_name)
    if not result:
        raise ValueError(f"Cannot find portal for {env_name}.")
    return result


def open_portal_url(*, env_name=ENV_NAME):
    portal_url = get_portal_url(env_name=env_name)
    try:
        subprocess.check_output(['curl', portal_url, '--silent', '--fail'])
    except subprocess.CalledProcessError as e:
        if e.returncode == 22:
            page_text = subprocess.check_output(['curl', portal_url, '--silent']).decode('utf-8')
            if 'waitress' in page_text:
                PRINT(f"The remote page, {portal_url}, exists but is getting a waitress error.")
                PRINT("Did you run the initial deployment action?")
                exit(1)
    subprocess.check_output(['open', portal_url])


class ResourceCommand:

    DESCRIPTION = "You need to set the DESCRIPTION attribute or write a description method."

    @classmethod
    def description(cls):
        return cls.DESCRIPTION

    @classmethod
    def execute(cls, **kwargs):
        if kwargs:
            raise ValueError(f"Unwanted keywod arguments: {kwargs}")
        raise NotImplementedError("You need to write an execute method.")

    @classmethod
    def add_arguments(cls, parser):
        return

    @classmethod
    def extract_arguments(cls, args):
        return {}

    @classmethod
    def main(cls, simulated_args=None):
        try:
            parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
                description=cls.description(),
                epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
            )
            cls.add_arguments(parser)
            args = parser.parse_args(args=simulated_args)

            cls.execute(**cls.extract_arguments(args))
        except Exception as e:
            PRINT(f"{e.__class__.__name__}: {e}")
            exit(1)


class CommonResourceCommand(ResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name', 'ecosystem', 'region']

    COMMON_ARGUMENT_NAME_INFO = [
        {'name': 'env_name', 'default': ENV_NAME},
        {'name': 'ecosystem', 'default': ECOSYSTEM},
        {'name': 'region', 'default': REGION},
    ]

    @classmethod
    def argument_default(cls, arg_name):
        return find_association(cls.COMMON_ARGUMENT_NAME_INFO, name=arg_name)['default']

    @classmethod
    def add_arguments(cls, parser):
        for arg_name in cls.COMMON_ARGUMENT_NAMES:
            default = cls.argument_default(arg_name)
            parser.add_argument("--" + hyphenify(arg_name), default=default,
                                help=f"name of {arg_name} (default {default})")
        super().add_arguments(parser)

    @classmethod
    def extract_arguments(cls, args):
        return dict(super().extract_arguments(args),
                    **dict({arg_name: getattr(args, arg_name)
                            for arg_name in cls.COMMON_ARGUMENT_NAMES}))


class ShowAttributeCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name', 'ecosystem']

    DESCRIPTION = "Shows named outputs"

    STACK_KIND = None  # a subclass will give this a value like 'network'

    ALLOW_NEWLINE = True

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument("name", default=None, help="comma-separated list of names")
        if cls.ALLOW_NEWLINE:
            parser.add_argument("--no-newline", default=True, action="store_false", dest="show_newline",
                                help="Whether to suppress the newline (default if --no-newline isn't supplied, False).")
        super().add_arguments(parser)

    @classmethod
    def extract_arguments(cls, args):
        return dict(super().extract_arguments(args),
                    name=args.name, show_newline=args.show_newline if cls.ALLOW_NEWLINE else False)

    @classmethod
    def execute(cls, *, name, env_name, ecosystem, show_newline):
        names = [subnet_name.strip() for subnet_name in name.split(",")]
        env_prefix = COMMON_STACK_PREFIX_CAMEL_CASE + camelize(cls.STACK_KIND) + camelize(env_name)
        eco_prefix = COMMON_STACK_PREFIX_CAMEL_CASE + camelize(cls.STACK_KIND) + camelize(ecosystem)
        found_outputs = []
        for output_name in names:
            output = (ConfigManager.find_stack_output(env_prefix + output_name, value_only=True) or
                      ConfigManager.find_stack_output(eco_prefix + output_name, value_only=True))
            if output is None:
                raise ValueError(f"The name {output_name} does not refer to a defined output.")
            found_outputs.append(output)
        PRINT(",".join(found_outputs), end="\n" if cls.ALLOW_NEWLINE and show_newline else "")


class ShowNetworkAttributeCommand(ShowAttributeCommand):

    STACK_KIND = 'network'


show_network_attribute_main = ShowNetworkAttributeCommand.main


class NetworkAttributeCommand(ShowAttributeCommand):

    STACK_KIND = 'network'
    ALLOW_NEWLINE = False


network_attribute_main = NetworkAttributeCommand.main


class ShowFoursightURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name', 'region']

    @classmethod
    def execute(cls, env_name, region):
        PRINT(get_foursight_url(region=region, env_name=env_name))


show_foursight_url_main = ShowFoursightURLCommand.main


class OpenFoursightURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name', 'region']

    @classmethod
    def execute(cls, *, env_name, region):
        open_foursight_url(env_name=env_name, region=region)


open_foursight_url_main = OpenFoursightURLCommand.main


class ShowPortalURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        PRINT(get_portal_url(env_name=env_name))


show_portal_url_main = ShowPortalURLCommand.main


class OpenPortalURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        open_portal_url(env_name=env_name)


open_portal_url_main = OpenPortalURLCommand.main
