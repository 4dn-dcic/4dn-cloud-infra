#from chalicelib.app import app
from chalice import Chalice

# Minimal app.py; used to initially verify packaging scripts
app = Chalice(app_name='foursight_cgap_trial')


@app.route('/')
def index():
    return {'minimal': 'foursight_cgap_trial'}
