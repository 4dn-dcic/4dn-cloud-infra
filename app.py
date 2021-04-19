import json
import logging
from chalicelib.app import DEFAULT_ENV
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
# from chalicelib.vars import FOURSIGHT_PREFIX
from chalice import Chalice, Response
from os.path import dirname

logging.basicConfig(encoding='utf8', level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_cgap_trial')

HOST = 'https://6kpcfpmbni.execute-api.us-east-1.amazonaws.com/api'
FOURSIGHT_PREFIX = 'foursight-cgap-mastertest'


class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup_dir = dirname(__file__)
    html_main_title = 'Foursight-CGAP-Trial'


logger.info('creating app utils object')
app_utils_obj = AppUtils()
logger.info('got app utils object')


@app.route('/', methods=['GET'])
def index():
    """
    Redirect with 302 to view page of DEFAULT_ENV
    Non-protected route
    """
    domain, context = app_utils_obj.get_domain_and_context(app.current_request.to_dict())
    logger.info('got domain and context for root route')
    resp_headers = {'Location': context + 'view/' + DEFAULT_ENV}
    return Response(status_code=302, body=json.dumps(resp_headers),
                    headers=resp_headers)


@app.route('/view/{environ}', methods=['GET'])
def view_route(environ):
    """
    Non-protected route
    """
    req_dict = app.current_request.to_dict()
    domain, context = app_utils_obj.get_domain_and_context(req_dict)
    logger.info('got domain and context for view: {}'.format(environ))
    return app_utils_obj.view_foursight(environ, app_utils_obj.check_authorization(req_dict, environ), domain, context)
