import json
import logging
import os

from chalice import Chalice
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import environ_bool, remove_suffix
from foursight_core.deploy import Deploy

from src.exceptions import CLIException
from src.constants import Settings


logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


DEBUG_CHALICE = environ_bool('DEBUG_CHALICE', default=False)
if DEBUG_CHALICE:
    logger.warning('debug mode on...')


######################
# Foursight App Config
######################
# Stripped down app designed only to be used for development purposes, NOT for
# actual deployment.


def get_deploy_variables():
    """Set required variables for successful app configuration.

    Look for environmental variables before falling back to custom
    directory.
    """
    es_host = os.environ.get("ES_HOST")
    environment_name = os.environ.get("ENV_NAME")
    environment_bucket = os.environ.get("GLOBAL_ENV_BUCKET")
    if es_host is None or environment_name is None or environment_bucket is None:
        es_host, environment_name, environment_bucket = configure_from_custom(
            es_host, environment_name, environment_bucket
        )
    foursight_prefix = remove_suffix("-envs", environment_bucket, required=True)
    return es_host, environment_name, environment_bucket, foursight_prefix


def configure_from_custom(es_host, environment_name, environment_bucket):
    """Configure un-set variables via custom configuration, if present.

    Catch error resulting from lack of custom configuration and provide
    feedback regarding variables that couldn't be configured.
    """
    found = {
        "ES_HOST": es_host,
        "GLOBAL_ENV_BUCKET": environment_bucket,
        "ENV_NAME": environment_name,
    }
    try:
        from src.base import ConfigManager
        from src.parts.datastore import C4DatastoreExports

        if es_host is None:
            es_host = C4DatastoreExports.get_es_url_with_port()
        found["ES_HOST"] = es_host
        if environment_bucket is None:
            environment_bucket = C4DatastoreExports.get_env_bucket()
            os.environ["GLOBAL_ENV_BUCKET"] = environment_bucket  # MUST be set
        found["GLOBAL_ENV_BUCKET"] = environment_bucket
        if environment_name is None:
            environment_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        found["ENV_NAME"] = environment_name
    except CLIException:
        raise RuntimeError(
            "Failed to configure app variables required for deployment. Please"
            " set environmental variables or configure custom directory appropriately."
            "\nCurrent configuration:\n%s"
            % json.dumps(found, indent=4)
        )
    return es_host, environment_name, environment_bucket


app = Chalice(app_name='foursight_cgap_development')
STAGE = os.environ.get('chalice_stage', 'prod')
HOST, DEFAULT_ENV, _GLOBAL_ENV_BUCKET, FOURSIGHT_PREFIX = get_deploy_variables()


class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup is moved to vendor/ where it will be automatically placed at top level
    check_setup_dir = os.path.dirname(os.path.dirname(__file__))
    # This will heuristically mostly title-case te DEFAULT_ENV but will put CGAP in all-caps.
    html_main_title = f'Foursight-{DEFAULT_ENV}'.title().replace("Cgap", "CGAP")  # was 'Foursight-CGAP-Mastertest'


########################
# Misc utility functions
########################


def compute_valid_deploy_stages():
    # TODO: Will wants to know why "test" is here. -kmp 17-Aug-2021
    return list(Deploy.CONFIG_BASE['stages'].keys()) + ['test']


class InvalidDeployStage(InvalidParameterError):

    @classmethod
    def compute_valid_options(cls):
        return compute_valid_deploy_stages()


def set_stage(stage):
    if stage not in compute_valid_deploy_stages():
        raise InvalidDeployStage(parameter='stage', value=stage)
    os.environ['chalice_stage'] = stage
