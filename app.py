# This is the main Chalice entry point Foursight;
# either Foursight-CGAP or Foursight-Fourfront.
#
import os
from dcicutils.env_utils import EnvUtils
from dcicutils.misc_utils import PRINT
from dcicutils.secrets_utils import assumed_identity


def _is_foursight_fourfront():
    """
    Returns True iff this is Foursight-Fourfront, in contrast to Foursight-CGAP.
    This will be called at RUNTIME at Chalice app startup in the deployed (in AWS) environment.
    """
    with assumed_identity():
        EnvUtils.init()
        return EnvUtils.app_case(if_cgap=False, if_fourfront=True)


# TODO: Better way to communicate this to foursight-cgap (chalicelib_cgap) or
# foursight (chalicelib_fourfront)? If this is set there then use it as the check_setup.json
# directory, otherwise use the local (chalicelib_cgap or chalicelib_fourfront) directory.
os.environ["FOURSIGHT_CHECK_SETUP_DIR"] = os.path.dirname(__file__)

# Note that foursight-cgap (chalicelib_cgap) and foursight (chalicelib_fourfrount) now
# live side-by-side; no longer (as of 2022-10-30) both packaging to chalicelib; nothing
# substantively magic about that name afterall. But this app.py file name IS magic (for
# Chalice) which is why it is here in 4dn-cloud-infra and pulls in either foursight-cgap
# or foursight (fourfront) depending on the is_foursight_fourfront function
if _is_foursight_fourfront():
    PRINT("Foursight-Fourfront: Including app_utils and check_schedules from chalicelib_fourfront.")
    from chalicelib_fourfront.app_utils import AppUtils
    from chalicelib_fourfront.check_schedules import *
else:
    PRINT("Foursight-CGAP: Including app_utils and check_schedules from chalicelib_cgap.")
    from chalicelib_cgap.app_utils import AppUtils
    from chalicelib_cgap.check_schedules import *
