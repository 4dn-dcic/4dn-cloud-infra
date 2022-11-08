import argparse
import boto3
import os
import subprocess

from dcicutils.cloudformation_utils import camelize
from dcicutils.misc_utils import find_association, PRINT
from ..base import ConfigManager, ENV_NAME, ECOSYSTEM, COMMON_STACK_PREFIX_CAMEL_CASE
from ..constants import Settings
from ..parts.ecs import C4ECSApplicationExports
from ..parts.sentieon import C4SentieonSupportExports


EPILOG = __doc__


REGION = 'us-east-1'  # TODO: make customizable


def hyphenify(x):
    return x.replace("_", "-")


# I didn't use the actual code snippets that were given, but this information was useful:
# https://stackoverflow.com/questions/36560504/how-do-i-find-the-api-endpoint-of-a-lambda-function

def get_foursight_url(*, env_name=ENV_NAME, region=REGION):
    if not os.environ.get("GLOBAL_ENV_BUCKET") and not os.environ.get("GLOBAL_BUCKET_ENV"):
        raise RuntimeError("Cannot compute the appropriate URL because GLOBAL_ENV_BUCKET is not bound.")
    api_gateway = boto3.client('apigateway')
    if region is None:
        region = api_gateway.meta.region_name
    if env_name is None:
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
    rest_apis = api_gateway.get_rest_apis()['items']
    foursight_api = find_association(rest_apis, name=lambda x: x.startswith("foursight_") or x.startswith("foursight-"))
    if not foursight_api:
        raise RuntimeError("There is no foursight api at this time.")
    foursight_api_id = foursight_api['id']
    # foursight_url = f"https://{foursight_api_id}.execute-api.{region}.amazonaws.com/api/view/{env_name}"
    foursight_url = f"https://{foursight_api_id}.execute-api.{region}.amazonaws.com/api"
    return foursight_url


def open_foursight_url(*, env_name=ENV_NAME, region=REGION):
    foursight_url = get_foursight_url(region=region, env_name=env_name)
    subprocess.check_output(['open', foursight_url])


def get_portal_url(*, env_name=ENV_NAME):
    if not os.environ.get("GLOBAL_ENV_BUCKET") and not os.environ.get("GLOBAL_BUCKET_ENV"):
        raise RuntimeError("Cannot compute the appropriate URL because GLOBAL_ENV_BUCKET is not bound.")
    result = C4ECSApplicationExports.get_application_url(env_name)
    if not result:
        raise ValueError(f"Cannot find portal for {env_name}.")
    return result


def get_sentieon_server_ip(*, env_name=ENV_NAME):
    if not os.environ.get("GLOBAL_ENV_BUCKET") and not os.environ.get("GLOBAL_BUCKET_ENV"):
        raise RuntimeError("Cannot compute the appropriate URL because GLOBAL_ENV_BUCKET is not bound.")
    result = C4SentieonSupportExports.get_server_ip(env_name)
    if not result:
        raise ValueError(f"Cannot find Sentieon server IP for {env_name}.")
    return result


def open_portal_url(*, env_name=ENV_NAME):
    """
    Attempts to open the portal home page, returning True if it probably did, or False if it knows it did not.
    In the failing situation (return value False), an explanatory error message will have been printed already.

    :param env_name: the environment name whose page use (default taken from custom/config.json)
    """
    portal_url = get_portal_url(env_name=env_name)
    return open_cgap_or_fourfront_url(portal_url)


def is_portal_uninitialized(*, sample_url):
    """
    This is a kind of blurry function that mostly creates an opportunity for a better error message
    before opening a URL for real.

    It returns True if the portal is probably not correctly spun up.
    It returns False if there was no obvious error in talking to the portal.
    Otherwise, if there was some other kind of error, that's reported by raising the error that was found.
    """
    try:
        subprocess.check_output(['curl', sample_url, '--silent', '--fail'])
    except subprocess.CalledProcessError as e:
        if e.returncode == 22:
            page_text = subprocess.check_output(['curl', sample_url, '--silent']).decode('utf-8')
            if 'waitress' in page_text:
                PRINT(f"The remote page, {sample_url}, exists but is getting a waitress error.")
                PRINT("Did you run the initial deployment action?")
                return True
        raise
    return False


def open_cgap_or_fourfront_url(url):
    """
    Attempts to open URL, returning True if it probably did, or False if it knows it did not.
    In the failing situation (return value False), an explanatory error message will have been printed already.

    NOTE: Although this function could open any URL, the error messages are optimized for opening a page
          on an orchestrated CGAP (or, one day, Fourfront) portal.

    :param url: The URL to open.
    """

    try:
        if is_portal_uninitialized(sample_url=url):
            return False
        subprocess.check_output(['open', url])
    except Exception as e:
        PRINT(f"An attempt was made to open {url}, but that failed with this message:\n{e}")
        return False
    return True


def get_health_page_url(*, env_name=ENV_NAME):
    portal_url = get_portal_url(env_name=env_name)
    health_page_url = portal_url + "/health?format=json"
    return health_page_url


def open_health_page_url(*, env_name=ENV_NAME):
    """
    Attempts to open the portal health page, returning True if it probably did, or False if it knows it did not.
    In the failing situation (return value False), an explanatory error message will have been printed already.

    :param env_name: the environment name whose page to use (default taken from custom/config.json)
    """
    health_page_url = get_health_page_url(env_name=env_name)
    return open_cgap_or_fourfront_url(health_page_url)


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
                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
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
    def find_output_values(cls, names, env_name=ENV_NAME, ecosystem=ECOSYSTEM):
        env_prefix = COMMON_STACK_PREFIX_CAMEL_CASE + camelize(cls.STACK_KIND) + camelize(env_name)
        eco_prefix = COMMON_STACK_PREFIX_CAMEL_CASE + camelize(cls.STACK_KIND) + camelize(ecosystem)
        found_output_values = []
        for output_name in names:
            output = (ConfigManager.find_stack_output(env_prefix + output_name, value_only=True) or
                      ConfigManager.find_stack_output(eco_prefix + output_name, value_only=True))
            if output is None:
                raise ValueError(f"The name {output_name} does not refer to a defined {cls.STACK_KIND} output.")
            found_output_values.append(output)
        return found_output_values

    @classmethod
    def find_attributes(cls, name, env_name=ENV_NAME, ecosystem=ECOSYSTEM):
        names = [segment.strip() for segment in name.split(",")]
        found_output_values = cls.find_output_values(names=names, env_name=env_name, ecosystem=ecosystem)
        return ",".join(found_output_values)

    @classmethod
    def execute(cls, *, name, env_name, ecosystem, show_newline):
        found_attributes = cls.find_attributes(name=name, env_name=env_name, ecosystem=ecosystem)
        PRINT(found_attributes, end="\n" if cls.ALLOW_NEWLINE and show_newline else "")


class ShowNetworkAttributeCommand(ShowAttributeCommand):
    STACK_KIND = 'network'


show_network_attribute_main = ShowNetworkAttributeCommand.main


class NetworkAttributeCommand(ShowNetworkAttributeCommand):
    ALLOW_NEWLINE = False


network_attribute_main = NetworkAttributeCommand.main


class ShowDatastoreAttributeCommand(ShowAttributeCommand):
    STACK_KIND = 'datastore'


show_datastore_attribute_main = ShowDatastoreAttributeCommand.main


class DatastoreAttributeCommand(ShowDatastoreAttributeCommand):
    ALLOW_NEWLINE = False


datastore_attribute_main = DatastoreAttributeCommand.main


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


class ShowSentieonServerIpCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        PRINT(get_sentieon_server_ip(env_name=env_name))


show_sentieon_server_ip_main = ShowSentieonServerIpCommand.main


class OpenPortalURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        open_portal_url(env_name=env_name)


open_portal_url_main = OpenPortalURLCommand.main


class ShowHealthPageURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        PRINT(get_health_page_url(env_name=env_name))


show_health_page_url_main = ShowHealthPageURLCommand.main


class OpenHealthPageURLCommand(CommonResourceCommand):

    COMMON_ARGUMENT_NAMES = ['env_name']

    @classmethod
    def execute(cls, *, env_name):
        open_health_page_url(env_name=env_name)


open_health_page_url_main = OpenHealthPageURLCommand.main
