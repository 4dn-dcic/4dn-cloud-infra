import argparse
import boto3
import subprocess

from dcicutils.misc_utils import find_association, PRINT
from ..base import ConfigManager, ENV_NAME
from ..constants import Settings
# from ..parts.datastore import C4DatastoreExports
from ..parts.ecs import C4ECSApplicationExports

EPILOG = __doc__


# I didn't use the actual code snippets that were given, but this information was useful:
# https://stackoverflow.com/questions/36560504/how-do-i-find-the-api-endpoint-of-a-lambda-function

def get_foursight_url(region=None, env_name=None):
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


def open_foursight_url(region=None, env_name=None):
    foursight_url = get_foursight_url(region=region, env_name=env_name)
    subprocess.check_output(['open', foursight_url])


def show_portal_url(env_name=None):
    env_name = env_name or ENV_NAME
    try:
        PRINT(C4ECSApplicationExports.get_application_url(env_name))
    except Exception as e:
        PRINT(f"{e.__class__.__name__}: {e}")
        exit(1)


def open_portal_url(region=None, env_name=None):
    env_name = env_name or ENV_NAME
    portal_url = C4ECSApplicationExports.get_application_url(env_name)
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


# Main functions beyond here...


def show_foursight_url_main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Show the name of foursight's web page.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", default=None, help="name of AWS region to use")
    parser.add_argument("--env_name", default=None, help="name of environment to configure")
    args = parser.parse_args(args=simulated_args)

    try:
        PRINT(get_foursight_url(region=args.region, env_name=args.env_name))
    except Exception as e:
        PRINT(f"{e.__class__.__name__}: {e}")
        exit(1)


def open_foursight_url_main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Show the name of foursight's web page.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--region", default=None, help="name of AWS region to use")
    parser.add_argument("--env_name", default=None, help="name of environment to configure")
    args = parser.parse_args(args=simulated_args)

    try:
        open_foursight_url(region=args.region, env_name=args.env_name)
    except Exception as e:
        PRINT(f"{e.__class__.__name__}: {e}")
        exit(1)


def show_portal_url_main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Show the name of the portal web page.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env_name", default=None, help="name of environment to configure")
    args = parser.parse_args(args=simulated_args)

    try:
        show_portal_url(env_name=args.env_name)
    except Exception as e:
        PRINT(f"{e.__class__.__name__}: {e}")
        exit(1)


def open_portal_url_main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Opent the portal web page.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env_name", default=None, help="name of environment to configure")
    args = parser.parse_args(args=simulated_args)

    try:
        open_portal_url(env_name=args.env_name)
    except Exception as e:
        PRINT(f"{e.__class__.__name__}: {e}")
        exit(1)
