import json
import logging
import os

from chalice import Chalice, Response, Cron
from chalicelib.app_utils import AppUtils as AppUtils_from_fourfront  # naming convention used in foursight
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import environ_bool, remove_suffix, ignored
from foursight_core.deploy import Deploy

logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


DEBUG_CHALICE = environ_bool('DEBUG_CHALICE', default=False)
if DEBUG_CHALICE:
    logger.warning('debug mode on...')


##################################
# Foursight (Fourfront) App Config
##################################


# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_fourfront')
STAGE = os.environ.get('chalice_stage', 'dev')
HOST = os.environ.get('ES_HOST', None)
DEFAULT_ENV = 'data'
FOURSIGHT_PREFIX = os.environ.get('FOURSIGHT_PREFIX')
if not FOURSIGHT_PREFIX:
    _GLOBAL_ENV_BUCKET = os.environ.get('GLOBAL_ENV_BUCKET') or os.environ.get('GLOBAL_BUCKET_ENV')
    if _GLOBAL_ENV_BUCKET is not None:
        print("_GLOBAL_ENV_BUCKET=", _GLOBAL_ENV_BUCKET)  # TODO: Temporary print statement, for debugging
        FOURSIGHT_PREFIX = remove_suffix("-envs", _GLOBAL_ENV_BUCKET, required=True)
        print(f"Inferred FOURSIGHT_PREFIX={FOURSIGHT_PREFIX}")
    else:
        raise RuntimeError("The FOURSIGHT_PREFIX environment variable is not set. Heuristics failed.")


DEFAULT_ENV = os.environ.get('ENV_NAME', "fourfront-uninitialized")


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
class AppUtils(AppUtils_from_fourfront):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    host = HOST
    package_name = 'chalicelib'
    # check_setup is moved to vendor/ where it will be automatically placed at top level
    check_setup_dir = os.path.dirname(__file__)
    html_main_title = f'Foursight-{DEFAULT_ENV}-{STAGE}'.title()


if DEBUG_CHALICE:
    logger.warning('creating app utils object')


app_utils_manager = SingletonManager(AppUtils)


'''######### SCHEDULED FXNS #########'''

def effectively_never():
    """Every February 31st, a.k.a. 'never'."""
    return Cron('0', '0', '31', '2', '?', '?')


def end_of_day_on_weekdays():
    """ Cron schedule that runs at 6pm EST (22:00 UTC) on weekdays. Used for deployments. """
    return Cron('0', '22', '?', '*', 'MON-FRI', '*')


def friday_at_8_pm_est():
    """ Creates a Cron schedule (in UTC) for Friday at 8pm EST """
    return Cron('0', '0', '?', '*', 'SAT', '*')  # 24 - 4 = 20 = 8PM


def monday_at_2_am_est():
    """ Creates a Cron schedule (in UTC) for every Monday at 2 AM EST """
    return Cron('0', '6', '?', '*', 'MON', '*')  # 6 - 4 = 2AM


# this dictionary defines the CRON schedules for the dev and prod foursight
# stagger them to reduce the load on Fourfront. Times are UTC
# info: https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html
foursight_cron_by_schedule = {
    'ten_min_checks': Cron('0/10', '*', '*', '*', '?', '*'),
    'thirty_min_checks': Cron('0/30', '*', '*', '*', '?', '*'),
    'hourly_checks_1': Cron('5', '0/1', '*', '*', '?', '*'),
    'hourly_checks_2': Cron('25', '0/1', '*', '*', '?', '*'),
    'hourly_checks_3': Cron('45', '0/1', '*', '*', '?', '*'),
    'morning_checks_1': Cron('0', '6', '*', '*', '?', '*'),
    'morning_checks_2': Cron('0', '7', '*', '*', '?', '*'),
    'morning_checks_3': Cron('0', '8', '*', '*', '?', '*'),
    'morning_checks_4': Cron('0', '9', '*', '*', '?', '*'),
    'monday_checks': Cron('0', '10', '?', '*', '2', '*'),
    'monthly_checks': Cron('0', '10', '1', '*', '?', '*'),
    'friday_autoscaling_checks': friday_at_8_pm_est(),
    'monday_autoscaling_checks': monday_at_2_am_est(),
    'manual_checks': effectively_never(),
    'deployment_checks': end_of_day_on_weekdays()
}


@app.schedule(foursight_cron_by_schedule['ten_min_checks'])
def ten_min_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'ten_min_checks')


@app.schedule(foursight_cron_by_schedule['thirty_min_checks'])
def thirty_min_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'thirty_min_checks')


@app.schedule(foursight_cron_by_schedule['hourly_checks_1'])
def hourly_checks_1(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'hourly_checks_1')


@app.schedule(foursight_cron_by_schedule['hourly_checks_2'])
def hourly_checks_2(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'hourly_checks_2')


@app.schedule(foursight_cron_by_schedule['hourly_checks_3'])
def hourly_checks_3(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'hourly_checks_3')


@app.schedule(foursight_cron_by_schedule['morning_checks_1'])
def morning_checks_1(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'morning_checks_1')


@app.schedule(foursight_cron_by_schedule['morning_checks_2'])
def morning_checks_2(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'morning_checks_2')


@app.schedule(foursight_cron_by_schedule['morning_checks_3'])
def morning_checks_3(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'morning_checks_3')


@app.schedule(foursight_cron_by_schedule['morning_checks_4'])
def morning_checks_4(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'morning_checks_4')


@app.schedule(foursight_cron_by_schedule['monday_checks'])
def monday_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'monday_checks')


@app.schedule(foursight_cron_by_schedule['monthly_checks'])
def monthly_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'monthly_checks')


@app.schedule(foursight_cron_by_schedule['deployment_checks'])
def deployment_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'deployment_checks')


@app.schedule(foursight_cron_by_schedule['friday_autoscaling_checks'])
def friday_autoscaling_checks(event):
    if STAGE == 'dev':
        return  # do not schedule autoscaling checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'friday_autoscaling_checks')


@app.schedule(foursight_cron_by_schedule['monday_autoscaling_checks'])
def monday_autoscaling_checks(event):
    if STAGE == 'dev':
        return  # do not schedule autoscaling checks on dev
    app_utils_manager.singleton.queue_scheduled_checks('all', 'monday_autoscaling_checks')


'''######### END SCHEDULED FXNS #########'''


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
    logger.warning('app-fourfront.py: In root route.')
    domain, context = app_utils_manager.singleton.get_domain_and_context(app.current_request.to_dict())
    logger.warning(f'app-fourfront.py: Got domain ({domain}) and context ({context}).')
    redirect_path = context + 'api/view/' + DEFAULT_ENV
    logger.warning(f'app-fourfront.py: Redirecting to: {redirect_path}')
    resp_headers = {'Location': redirect_path}  # special casing 'api' for the chalice app root
    return Response(status_code=302, body=json.dumps(resp_headers), headers=resp_headers)


@app.route('/introspect', methods=['GET'])
def introspect(environ):
    """
    Test route
    """
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
    return app_utils_manager.singleton.view_foursight(app.current_request, environ, app_utils_manager.singleton.check_authorization(req_dict, environ), domain, context)


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


@app.route('/environments/{environ}', methods=['PUT'])
def put_environment(environ):
    """
    Take a PUT request that has a json payload with 'fourfront' (ff server)
    and 'es' (es server).
    Attempts to generate an new environment and runs all checks initially
    if successful.
    Protected route
    """
    request = app.current_request
    if app_utils_manager.singleton.check_authorization(request.to_dict(), environ):
        env_data = request.json_body
        return app_utils_manager.singleton.run_put_environment(environ, env_data)
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


@app.route('/environments/{environ}/delete', methods=['DELETE'])
def delete_environment(environ):
    """
    Takes a DELETE request and purges the foursight environment specified by 'environ'.
    NOTE: This only de-schedules all checks, it does NOT wipe data associated with this
    environment - that can only be done directly from S3 (for safety reasons).
    Protected route
    """
    if app_utils_manager.singleton.check_authorization(app.current_request.to_dict(), environ):  # TODO (C4-138) Centralize authorization check
        return app_utils_manager.singleton.run_delete_environment(environ)
    else:
        return app_utils_manager.singleton.forbidden_response()


# dmichaels/2022-08-09:
# For testing/debugging/troubleshooting.
@app.route('/info/{environ}', methods=['GET'])
def get_view_info_route(environ):
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    is_admin = app_utils_manager.singleton.check_authorization(req_dict, environ)
    return app_utils_manager.singleton.view_info(request=app.current_request, environ=environ, is_admin=is_admin, domain=domain, context=context)


@app.route('/users/{environ}/{email}', methods=['GET'])
def get_view_user_route(environ, email):
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    is_admin = app_utils_manager.singleton.check_authorization(req_dict, environ)
    return app_utils_manager.singleton.view_user(request=app.current_request, environ=environ, is_admin=is_admin, domain=domain, context=context, email=email)


@app.route('/users/{environ}', methods=['GET'])
def get_view_users_route(environ):
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    is_admin = app_utils_manager.singleton.check_authorization(req_dict, environ)
    return app_utils_manager.singleton.view_users(request=app.current_request, environ=environ, is_admin=is_admin, domain=domain, context=context)


# dmichaels/2022-08-12:
# For testing/debugging/troubleshooting.
@app.route('/reload_lambda/{environ}/{lambda_name}', methods=['GET'])
def get_view_reload_lambda_route(environ, lambda_name):
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_manager.singleton.get_domain_and_context(req_dict)
    is_admin = app_utils_manager.singleton.check_authorization(req_dict, environ)
    return app_utils_manager.singleton.view_reload_lambda(request=app.current_request, environ=environ, is_admin=is_admin, domain=domain, context=context, lambda_name=lambda_name)


######### PURE LAMBDA FUNCTIONS #########


@app.lambda_function()
def check_runner(event, context):
    """
    Pure lambda function to pull run and check information from SQS and run
    the checks. Self propogates. event is a dict of information passed into
    the lambda at invocation time.
    """
    if not event:
        return
    app_utils_manager.singleton.run_check_runner(event)


######### MISC UTILITY FUNCTIONS #########


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


