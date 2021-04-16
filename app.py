import json
from chalicelib.app import app_utils_obj, DEFAULT_ENV
from chalice import Chalice, Response

# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_cgap_trial')


@app.route('/', methods=['GET'])
def index():
    """
    Redirect with 302 to view page of DEFAULT_ENV
    Non-protected route
    """
    domain, context = app_utils_obj.get_domain_and_context(app.current_request.to_dict())
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
    return app_utils_obj.view_foursight(environ, app_utils_obj.check_authorization(req_dict, environ), domain, context)
