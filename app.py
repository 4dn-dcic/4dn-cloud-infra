import json
import logging
# from chalicelib.app import app
# from chalicelib.app import DEFAULT_ENV
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
# from chalicelib.vars import FOURSIGHT_PREFIX
from chalice import Chalice, Response
from os.path import dirname

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_cgap_trial')

HOST = 'https://6kpcfpmbni.execute-api.us-east-1.amazonaws.com/api'
FOURSIGHT_PREFIX = 'foursight-cgap-mastertest'
DEFAULT_ENV = 'cgap-mastertest'


class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup_dir = dirname(__file__)  # This file is present in chalicelib
    html_main_title = 'Foursight-CGAP-Mastertest'


logger.warning('creating app utils object')
app_utils_obj = AppUtils()
logger.warning('got app utils object')


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
    domain, context = app_utils_obj.get_domain_and_context(app.current_request.to_dict())
    logger.warning('got domain and context for root route')
    resp_headers = {'Location': context + 'api/view/' + DEFAULT_ENV}  # special casing 'api' for the chalice app root
    return Response(status_code=302, body=json.dumps(resp_headers),
                    headers=resp_headers)


@app.route('/view/{environ}', methods=['GET'])
def view_route(environ):
    """
    Non-protected route
    """
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    logger.warning('got domain and context for view: {}'.format(environ))
    return app_utils_obj.view_foursight(environ, app_utils_obj.check_authorization(req_dict, environ), domain, context)
