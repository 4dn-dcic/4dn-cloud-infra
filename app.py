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


def _is_foursight_cgap():
    """
    Returns True iff this is Foursight-cgap, in contrast to Foursight-fourfront or foursight-smaht.
    This will be called at RUNTIME at Chalice app startup in the deployed (in AWS) environment.
    """
    with assumed_identity():
        EnvUtils.init()
        return EnvUtils.app_case(if_cgap=False, if_fourfront=True)


# TODO: Better way to communicate the directory containing the check_setup.json
# file to foursight-cgap (chalicelib_cgap) or foursight (chalicelib_fourfront)?
#
# If this FOURSIGHT_CHECK_SETUP_DIR environment variable is set there then use it as the
# check_setup.json directory (but only if it contains a non-empty check_setup.json file);
# otherwise use the local directory chalicelib_cgap or chalicelib_fourfront in foursight-cgap
# or foursight, respectively.
#
# The check_setup.json file here (in 4dn-cloud-infra) gets there by virtue of the pyproject
# resolve-foursight-checks command, which now BTW takes a --app argument to indicate if the
# file should be for Foursight-CGAP or Foursight-Fourfront. This command pulls check_setup.json
# from either the chalicelib_cgap or chalicelib_fourfront directories of foursight-cgap or
# fourfront, respectively; and it expands any <env-name> placeholders within it to the given
# environment name. However, this expansion is now also done at runtime by Foursight, using
# the default environment name, so running resolve-foursight-checks is now not strictly necesssary.

# TODO
# Don't think we need to do this anymore now that we automatically pickup check_setup.json
# from either chalicelib_foursight/check_setup.json or chalicelib_cgap/check_setup.json
# as appropriate; this being done in foursight_core.app.AppUtilsCore.__init__ via the
# _locate_check_setup_file function there (and expanding <env-name> as appropriate
# obviating the need for resolve-foursight-checks as mentioned above). Doing the
# below will force that lookup to look here for check_setup.json instead, which
# would assume that you did the appropriate resolve-foursight-checks here manually.
#
if not os.environ.get("FOURSIGHT_CHECK_SETUP_DIR", None):
    os.environ["FOURSIGHT_CHECK_SETUP_DIR"] = os.path.dirname(__file__)

# Note that foursight-cgap (chalicelib_cgap) and foursight (chalicelib_fourfrount) now
# live side-by-side; no longer (as of 2022-10-30) both packaging to chalicelib; nothing
# substantively magic about that name afterall. But this app.py file name IS magic (for
# Chalice) which is why it is here in 4dn-cloud-infra and pulls in either foursight-cgap
# or foursight (fourfront) depending on the _is_foursight_fourfront function above.
if _is_foursight_fourfront():
    PRINT("Foursight-Fourfront: Importing app_utils and check_schedules from chalicelib_fourfront.")
    from chalicelib_fourfront.app_utils import AppUtils
    from chalicelib_fourfront.check_schedules import *
elif _is_foursight_cgap():
    PRINT("Foursight-CGAP: Importing app_utils and check_schedules from chalicelib_cgap.")
    from chalicelib_cgap.app_utils import AppUtils
    from chalicelib_cgap.check_schedules import *
else:
    PRINT("Foursight-smaht: Importing app_utils and check_schedules from chalicelib_smaht.")
    from chalicelib_smaht.app_utils import AppUtils
    from chalicelib_smaht.check_schedules import *
