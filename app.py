import os
from dcicutils.secrets_utils import assumed_identity
from dcicutils.env_utils import EnvUtils
from foursight_core.app_utils import app


def is_foursight_fourfront():
    with assumed_identity():
        EnvUtils.init()
        is_foursight_fourfront = EnvUtils.app_case(if_cgap=False, if_fourfront=True)
        return is_foursight_fourfront


# TODO: Better way to communicate this to foursight-cgap (chalicelib_cgap) or foursight (chalicelib_fourfront)?
os.environ["FOURSIGHT_CHECK_SETUP_DIR"] = os.path.dirname(__file__)

# Note that foursight-cgap (chalicelib_cgap) and foursight (chalicelib_fourfrount) now
# live side-by-side; no longer (as of 2022-10-30) both packaging to chalicelib; nothing
# substantively magic about that name afterall. But this app.py file name IS magic (for
# Chalice) which is why it is here in 4dn-cloud-infra and pulls in either foursight-cgap
# or foursight (fourfront) depending on the is_foursight_fourfront function
if is_foursight_fourfront():
    from chalicelib_fourfront.app_utils import AppUtils
    from chalicelib_fourfront.check_schedules import *
else:
    from chalicelib_cgap.app_utils import AppUtils
    from chalicelib_cgap.check_schedules import *
