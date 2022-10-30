import os
from foursight_core.app_utils import app

# TODO: Right way to indicate this is foursight-cgap/chalicelib_cgap or foursight/chalicelib_fourfront?
# The way it is done here/below is very lame temporary.
def IS_FOURSIGHT_FOURFRONT():
    if os.environ.get("FOURSIGHT_FOURFRONT", None) == "1":
        return True
    identity = os.environ.get("IDENTITY");
    if identity:
        identity = identity.lower()
        if "fourfront" in identity:
            return True
    return False

# TODO: Better way to communicate this to foursight-cgap (chalicelib_cgap) or foursight (chalicelib_fourfront)?
os.environ["FOURSIGHT_CHECK_SETUP_DIR"] = os.path.dirname(__file__)

# Note that foursight-cgap (chalicelib_cgap) and foursight (chalicelib_fourfrount) now live side-by-side;
# no longer (as of 2022-10-30) both packaging to chalicelib; nothing substantively magic about that name afterall.
# But this app.py file name is magic (for Chalice) which is why it is here in 4dn-cloud-infra and pulls in either
# foursight-cgap (chalicelib_cgap) or foursight (chalicelib_fourfrount) depending on, currently, the setting of
# FOURSIGHT_FOURFRONT environment variable. TODO: How to determine this at run (post-deploy) time.
if IS_FOURSIGHT_FOURFRONT():
    from chalicelib_fourfront.app_utils import AppUtils
    from chalicelib_fourfront.check_schedules import *
else:
    from chalicelib_cgap.app_utils import AppUtils
    from chalicelib_cgap.check_schedules import *
