import json
import logging
import os

from chalice import Chalice, Response, Cron
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import environ_bool, remove_suffix, ignored
from foursight_core.deploy import Deploy


logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


DEBUG_CHALICE = environ_bool('DEBUG_CHALICE', default=False)
if DEBUG_CHALICE:
    logger.warning('debug mode on...')


############################################
# Foursight (CGAP) App Config for Deployment
############################################


app = Chalice(app_name='foursight_cgap_trial')
STAGE = os.environ.get('chalice_stage', 'dev')
HOST = os.environ.get("ES_HOST")

# previously FOURSIGHT_PREFIX = 'foursight-cgap-mastertest'  # TODO: This should probably just be "foursight-cgap"
FOURSIGHT_PREFIX = os.environ.get('FOURSIGHT_PREFIX')
if not FOURSIGHT_PREFIX:
    _GLOBAL_ENV_BUCKET = os.environ.get("GLOBAL_ENV_BUCKET") or os.environ.get("GLOBAL_BUCKET_ENV")
    if _GLOBAL_ENV_BUCKET is not None:
        print("_GLOBAL_ENV_BUCKET=", _GLOBAL_ENV_BUCKET)  # TODO: Temporary print statement, for debugging
        FOURSIGHT_PREFIX = remove_suffix("-envs", _GLOBAL_ENV_BUCKET, required=True)
        print(f"Inferred FOURSIGHT_PREFIX={FOURSIGHT_PREFIX}")
    else:
        raise RuntimeError("The FOURSIGHT_PREFIX environment variable is not set. Heuristics failed.")

DEFAULT_ENV = os.environ.get("ENV_NAME", "cgap-uninitialized")


class SingletonManager():  # TODO: Move to dcicutils

    def __init__(self, singleton_class, *singleton_args, **singleton_kwargs):
        self._singleton = None
        self._singleton_class = singleton_class
        self._singleton_args = singleton_args
        self._singleton_kwargs = singleton_kwargs

    @property
    def singleton(self):
        if not self._singleton:
            self._singleton = self._singleton_class(*self._singleton_args or (), **self._singleton_kwargs or {})
        return self._singleton


# This object usually in chalicelib/app_utils.py
class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap-dbmi.hms.harvard.edu/favicon.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup is moved to vendor/ where it will be automatically placed at top level
    check_setup_dir = os.path.dirname(__file__)
    # This will heuristically mostly title-case te DEFAULT_ENV but will put CGAP in all-caps.
    html_main_title = f'Foursight-{DEFAULT_ENV}'.title().replace("Cgap", "CGAP")  # was 'Foursight-CGAP-Mastertest'


if DEBUG_CHALICE:
    logger.warning('creating app utils object')


# TODO: Will asks if this isn't redundant with other things done to keep this from being re-evaluated.
#       We weren't sure and will look again at this another time. -kmp 17-Aug-2021
app_utils_manager = SingletonManager(AppUtils)


if DEBUG_CHALICE:
    logger.warning('got app utils object')


######################
# Foursight Scheduling
######################


def effectively_never():
    """Every February 31st, a.k.a. 'never'."""
    return Cron('0', '0', '31', '2', '?', '*')


def morning_10am_utc():
    """ Schedule for every morning at 10AM UTC (6AM EST) """
    return Cron('0', '10', '*', '*', '?', '*')


foursight_cron_by_schedule = {
    'prod': {
        'ten_min_checks': Cron('0/10', '*', '*', '*', '?', '*'),
        'fifteen_min_checks': Cron('0/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_2': Cron('5/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_3': Cron('10/15', '*', '*', '*', '?', '*'),
        'thirty_min_checks': Cron('0/30', '*', '*', '*', '?', '*'),
        'hourly_checks': Cron('0', '0/1', '*', '*', '?', '*'),
        'hourly_checks_2': Cron('15', '0/1', '*', '*', '?', '*'),
        'early_morning_checks': Cron('0', '8', '*', '*', '?', '*'),
        'morning_checks': Cron('0', '10', '*', '*', '?', '*'),
        'morning_checks_2': Cron('15', '10', '*', '*', '?', '*'),
        'evening_checks': Cron('0', '22', '*', '*', '?', '*'),
        'monday_checks': Cron('0', '9', '?', '*', '2', '*'),
        'monthly_checks': Cron('0', '9', '1', '*', '?', '*'),
        'manual_checks': effectively_never(),
    },
    'dev': {
        'ten_min_checks': Cron('5/10', '*', '*', '*', '?', '*'),
        'fifteen_min_checks': Cron('0/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_2': Cron('5/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_3': Cron('10/15', '*', '*', '*', '?', '*'),
        'thirty_min_checks': Cron('15/30', '*', '*', '*', '?', '*'),
        'hourly_checks': Cron('30', '0/1', '*', '*', '?', '*'),
        'hourly_checks_2': Cron('45', '0/1', '*', '*', '?', '*'),
        'early_morning_checks': Cron('0', '8', '*', '*', '?', '*'),
        'morning_checks': Cron('30', '10', '*', '*', '?', '*'),
        'morning_checks_2': Cron('45', '10', '*', '*', '?', '*'),
        'evening_checks': Cron('0', '22', '*', '*', '?', '*'),
        'monday_checks': Cron('30', '9', '?', '*', '2', '*'),
        'monthly_checks': Cron('30', '9', '1', '*', '?', '*'),
        'manual_checks': effectively_never(),
    }
}


@app.schedule(foursight_cron_by_schedule[STAGE]['manual_checks'])
def manual_checks():
    app_utils_manager.singleton.queue_scheduled_checks('all', 'manual_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['morning_checks'])
def morning_checks(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'morning_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks'])
def fifteen_min_checks(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'fifteen_min_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks_2'])
def fifteen_min_checks_2(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'fifteen_min_checks_2')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks_3'])
def fifteen_min_checks_3(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'fifteen_min_checks_3')


@app.schedule(foursight_cron_by_schedule[STAGE]['hourly_checks'])
def hourly_checks(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'hourly_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['hourly_checks_2'])
def hourly_checks_2(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'hourly_checks_2')


@app.schedule(foursight_cron_by_schedule[STAGE]['monthly_checks'])
def monthly_checks(event):
    ignored(event)
    app_utils_manager.singleton.queue_scheduled_checks('all', 'monthly_checks')


###############################
# Foursight Route Configuration
###############################


@app.route('/callback')
def auth0_callback():
    """
    Special callback route, only to be used as a callback from auth0
    Will return a redirect to view on error/any missing callback info.
    """
    request = app.current_request
    return app_utils_manager.singleton.auth0_callback(request, DEFAULT_ENV)


@app.route('/', methods=['GET'])
def index():
    """
    Redirect with 302 to view page of DEFAULT_ENV
    Non-protected route
    """
    logger.warning('in root route')
    domain, context = app_utils_manager.singleton.get_domain_and_context(app.current_request.to_dict())
    logger.warning('got domain and context')
    resp_headers = {'Location': context + 'api/view/' + DEFAULT_ENV}  # special casing 'api' for the chalice app root
    return Response(status_code=302, body=json.dumps(resp_headers),
                    headers=resp_headers)


@app.route('/introspect', methods=['GET'])
def introspect(environ):
    """
    Test route
    """
    logger.warning('in introspect route')
    auth = app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ)
    if auth:
        return Response(status_code=200, body=json.dumps(app.current_request.to_dict()))
    else:
        return app_utils_manager.singleton.forbidden_response()


@app.route('/view_run/{environ}/{check}/{method}', methods=['GET'])
def view_run_route(environ, check, method):
    """
    Protected route
    """
    logger.warning('in view_run route for {} {} {}'.format(environ, check, method))
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    query_params = req_dict.get('query_params', {})
    if app_utils_manager.singleton.check_authorization(req_dict, environ):
        if method == 'action':
            return app_utils_manager.singleton.view_run_action(environ, check, query_params, context)
        else:
            return app_utils_manager.singleton.view_run_check(environ, check, query_params, context)
    else:
        return app_utils_manager.singleton.forbidden_response(context)


@app.route('/view/{environ}', methods=['GET'])
def view_route(environ):
    """
    Non-protected route
    """
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    check_authorization = app_utils_manager.singleton.check_authorization(req_dict, environ)
    logger.warning(f'result of check authorization: {check_authorization}')
    return app_utils_manager.singleton.view_foursight(app.current_request, environ, check_authorization, domain, context)


@app.route('/view/{environ}/{check}/{uuid}', methods=['GET'])
def view_check_route(environ, check, uuid):
    """
    Protected route
    """
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    if app_utils_manager.singleton.check_authorization(req_dict, environ):
        return app_utils_manager.singleton.view_foursight_check(app.current_request, environ, check, uuid, True, domain, context)
    else:
        return app_utils_manager.singleton.forbidden_response()


@app.route('/history/{environ}/{check}', methods=['GET'])
def history_route(environ, check):
    """
    Non-protected route
    """
    # get some query params
    req_dict = app.current_request.to_dict()
    query_params = req_dict.get('query_params')
    start = int(query_params.get('start', '0')) if query_params else 0
    limit = int(query_params.get('limit', '25')) if query_params else 25
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    return app_utils_manager.singleton.view_foursight_history(app.current_request, environ, check, start, limit,
                                                app_utils_manager.singleton.check_authorization(req_dict, environ), domain, context)


@app.route('/checks/{environ}/{check}/{uuid}', methods=['GET'])
def get_check_with_uuid_route(environ, check, uuid):
    """
    Protected route
    """
    if app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_manager.singleton.run_get_check(environ, check, uuid)
    else:
        return app_utils_manager.singleton.forbidden_response()


@app.route('/checks/{environ}/{check}', methods=['GET'])
def get_check_route(environ, check):
    """
    Protected route
    """
    if app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_manager.singleton.run_get_check(environ, check, None)
    else:
        return app_utils_manager.singleton.forbidden_response()


@app.route('/checks/{environ}/{check}', methods=['PUT'])
def put_check_route(environ, check):
    """
    Take a PUT request. Body of the request should be a json object with keys
    corresponding to the fields in CheckResult, namely:
    title, status, description, brief_output, full_output, uuid.
    If uuid is provided and a previous check is found, the default
    behavior is to append brief_output and full_output.

    Protected route
    """
    request = app.current_request
    if app_utils_manager.singleton.check_authorization(request.to_dict(), environ):
        put_data = request.json_body
        return app_utils_manager.singleton.run_put_check(environ, check, put_data)
    else:
        return app_utils_manager.singleton.forbidden_response()


@app.route('/environments/{environ}', methods=['GET'])
def get_environment_route(environ):
    """
    Protected route
    """
    if app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_manager.singleton.run_get_environment(environ)
    else:
        return app_utils_manager.singleton.forbidden_response()

# NOTE: the environment is created through this repository, so this API
#       should be unnecessary.
# @app.route('/environments/{environ}', methods=['PUT'])
# def put_environment(environ):
#     """
#     Take a PUT request that has a json payload with 'fourfront' (ff server)
#     and 'es' (es server).
#     Attempts to generate an new environment and runs all checks initially
#     if successful.
#
#     Protected route
#     """
#     request = app.current_request
#     if app_utils_manager.singleton.check_authorization(request.to_dict(), environ):
#         env_data = request.json_body
#         return app_utils_manager.singleton.run_put_environment(environ, env_data)
#     else:
#         return app_utils_manager.singleton.forbidden_response()


# NOTE: this functionality is disabled for safety reasons.
#       orchestrations through 4dn-cloud-infra only have one environment,
#       so a user should never want to do this anyway. - Will 5/27/21
# @app.route('/environments/{environ}/delete', methods=['DELETE'])
# def delete_environment(environ):
#     """
#     Takes a DELETE request and purges the foursight environment specified by 'environ'.
#     NOTE: This only de-schedules all checks, it does NOT wipe data associated with this
#     environment - that can only be done directly from S3 (for safety reasons).
#
#     Protected route
#     """
#     # TODO (C4-138) Centralize authorization check
#     if app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ):
#         return app_utils_manager.singleton.run_delete_environment(environ)
#     else:
#         return app_utils_manager.singleton.forbidden_response()


# dmichaels/2022-08-01:
# For testing/debugging/troubleshooting.
@app.route('/view/info', methods=['GET'])
def get_view_info_route():
    if app_utils_obj.check_authorization(app.current_request.to_dict()):
        return app_utils_manager.singleton.view_info(app.current_request)
    else:
        return app_utils_obj.forbidden_response()


#######################
# Pure lambda functions
#######################

@app.lambda_function()
def check_runner(event, context):
    """
    Pure lambda function to pull run and check information from SQS and run
    the checks. Self propogates. event is a dict of information passed into
    the lambda at invocation time.
    """
    ignored(context)
    if not event:
        return
    app_utils_manager.singleton.run_check_runner(event)


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


def set_timeout(timeout):
    app_utils_manager.singleton.set_timeout(timeout)

