import os
import json
import logging
# from chalicelib.app import app
# from chalicelib.app import DEFAULT_ENV
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
# from chalicelib.vars import FOURSIGHT_PREFIX
from chalice import Chalice, Response, Cron
from foursight_core.deploy import Deploy
from dcicutils.misc_utils import environ_bool
from dcicutils.ff_utils import get_metadata
import traceback


logging.basicConfig(level=logging.DEBUG, format='%(asctime)-15s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


DEBUG_CHALICE = environ_bool('DEBUG_CHALICE', default=False)
if DEBUG_CHALICE:
    logger.warning('debug mode on...')


# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_cgap_trial')


# XXX: acquire through args?
HOST = os.environ.get('ES_HOST', None)
FOURSIGHT_PREFIX = 'foursight-cgap-mastertest'
DEFAULT_ENV = 'cgap-mastertest'


def effectively_never():
    """Every February 31st, a.k.a. 'never'."""
    return Cron('0', '0', '31', '2', '?', '*')


class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup_dir = dirname(__file__)  # This file is present in chalicelib
    html_main_title = 'Foursight-CGAP-Mastertest'


if DEBUG_CHALICE:
    logger.warning('creating app utils object')

app_utils_obj = AppUtils()

if DEBUG_CHALICE:
    logger.warning('got app utils object')


@app.schedule(effectively_never())
def manual_checks():
    app_utils_obj.queue_scheduled_checks('all', 'manual_checks')


@app.route('/callback')
def auth0_callback():
    """
    Special callback route, only to be used as a callback from auth0
    Will return a redirect to view on error/any missing callback info.
    """
    request = app.current_request
    return app_utils_obj.auth0_callback(request, DEFAULT_ENV)


@app.route('/', methods=['GET'])
def index():
    """
    Redirect with 302 to view page of DEFAULT_ENV
    Non-protected route
    """
    logger.warning('in root route')
    domain, context = app_utils_obj.get_domain_and_context(app.current_request.to_dict())
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
    auth = app_utils_obj.check_authorization(app.current_request.to_dict(), environ)
    if auth:
        return Response(status_code=200, body=json.dumps(app.current_request.to_dict()))
    else:
        return app_utils_obj.forbidden_response()


@app.route('/view_run/{environ}/{check}/{method}', methods=['GET'])
def view_run_route(environ, check, method):
    """
    Protected route
    """
    logger.warning('in view_run route for {} {} {}'.format(environ, check, method))
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    query_params = req_dict.get('query_params', {})
    if app_utils_obj.check_authorization(req_dict, environ):
        if method == 'action':
            return app_utils_obj.view_run_action(environ, check, query_params, context)
        else:
            return app_utils_obj.view_run_check(environ, check, query_params, context)
    else:
        return app_utils_obj.forbidden_response(context)


@app.route('/view/{environ}', methods=['GET'])
def view_route(environ):
    """
    Non-protected route
    """
    req_dict = app.current_request.to_dict()
    logger.warning('req_dict in /view/{environ}')
    logger.warning(req_dict)
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    logger.warning('domain, context in /view/{environ}')
    logger.warning(domain)
    logger.warning(context)
    check_authorization = app_utils_obj.check_authorization(req_dict, environ)
    logger.warning('result of check authorization: {}'.format(check_authorization))

    # testing the auth
    import jwt
    from base64 import b64decode
    token = app_utils_obj.get_jwt(req_dict)
    auth0_client = os.environ.get('CLIENT_ID', None)
    auth0_secret = os.environ.get('CLIENT_SECRET', None)
    if token:
        payload = jwt.decode(token, b64decode(auth0_secret, '-_'), audience=auth0_client, leeway=30)
        for env_info in app_utils_obj.init_environments(environ).values():
            obj_id = 'users/' + payload.get('email').lower()
            logger.warning('get_metadata with obj_id: {}, ff_env: {}'.format(obj_id, env_info['ff_env']))
            user_res = get_metadata(obj_id,
                                    key=req_dict, add_on='frame=object')
            logger.error(env_info)
            logger.error(user_res)

    return app_utils_obj.view_foursight(environ, check_authorization, domain, context)


@app.route('/view/{environ}/{check}/{uuid}', methods=['GET'])
def view_check_route(environ, check, uuid):
    """
    Protected route
    """
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    if app_utils_obj.check_authorization(req_dict, environ):
        return app_utils_obj.view_foursight_check(environ, check, uuid, True, domain, context)
    else:
        return app_utils_obj.forbidden_response()


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
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    return app_utils_obj.view_foursight_history(environ, check, start, limit,
                                                app_utils_obj.check_authorization(req_dict, environ), domain, context)


@app.route('/checks/{environ}/{check}/{uuid}', methods=['GET'])
def get_check_with_uuid_route(environ, check, uuid):
    """
    Protected route
    """
    if app_utils_obj.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_obj.run_get_check(environ, check, uuid)
    else:
        return app_utils_obj.forbidden_response()


@app.route('/checks/{environ}/{check}', methods=['GET'])
def get_check_route(environ, check):
    """
    Protected route
    """
    if app_utils_obj.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_obj.run_get_check(environ, check, None)
    else:
        return app_utils_obj.forbidden_response()


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
    if app_utils_obj.check_authorization(request.to_dict(), environ):
        put_data = request.json_body
        return app_utils_obj.run_put_check(environ, check, put_data)
    else:
        return app_utils_obj.forbidden_response()


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
    if app_utils_obj.check_authorization(request.to_dict(), environ):
        env_data = request.json_body
        return app_utils_obj.run_put_environment(environ, env_data)
    else:
        return app_utils_obj.forbidden_response()


@app.route('/environments/{environ}', methods=['GET'])
def get_environment_route(environ):
    """
    Protected route
    """
    if app_utils_obj.check_authorization(app.current_request.to_dict(), environ):
        return app_utils_obj.run_get_environment(environ)
    else:
        return app_utils_obj.forbidden_response()


@app.route('/environments/{environ}/delete', methods=['DELETE'])
def delete_environment(environ):
    """
    Takes a DELETE request and purges the foursight environment specified by 'environ'.
    NOTE: This only de-schedules all checks, it does NOT wipe data associated with this
    environment - that can only be done directly from S3 (for safety reasons).

    Protected route
    """
    if app_utils_obj.check_authorization(app.current_request.to_dict(), environ):  # TODO (C4-138) Centralize authorization check
        return app_utils_obj.run_delete_environment(environ)
    else:
        return app_utils_obj.forbidden_response()


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
    app_utils_obj.run_check_runner(event)


######### MISC UTILITY FUNCTIONS #########


def set_stage(stage):
    if stage != 'test' and stage not in Deploy.CONFIG_BASE['stages']:
        print('ERROR! Input stage is not valid. Must be one of: %s' % str(list(Deploy.CONFIG_BASE['stages'].keys()).extend('test')))
    os.environ['chalice_stage'] = stage


def set_timeout(timeout):
    app_utils_obj.set_timeout(timeout)
