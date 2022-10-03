import os

from chalice import Chalice, Response, Cron
from chalicelib.app_utils import AppUtils as AppUtils_from_cgap  # naming convention used in foursight-cgap
from foursight_core.app_utils import app
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import environ_bool, remove_suffix, ignored
from foursight_core.deploy import Deploy


############################################
# Foursight (CGAP) App Config for Deployment
############################################


STAGE = os.environ.get('chalice_stage', 'dev')
HOST = os.environ.get('ES_HOST', None)
# previously FOURSIGHT_PREFIX = 'foursight-cgap-mastertest'  # TODO: This should probably just be 'foursight-cgap'
FOURSIGHT_PREFIX = os.environ.get('FOURSIGHT_PREFIX')
if not FOURSIGHT_PREFIX:
    _GLOBAL_ENV_BUCKET = os.environ.get('GLOBAL_ENV_BUCKET') or os.environ.get('GLOBAL_BUCKET_ENV')
    if _GLOBAL_ENV_BUCKET is not None:
        print('_GLOBAL_ENV_BUCKET=', _GLOBAL_ENV_BUCKET)  # TODO: Temporary print statement, for debugging
        FOURSIGHT_PREFIX = remove_suffix('-envs', _GLOBAL_ENV_BUCKET, required=True)
        print(f'Inferred FOURSIGHT_PREFIX={FOURSIGHT_PREFIX}')
    else:
        raise RuntimeError('The FOURSIGHT_PREFIX environment variable is not set. Heuristics failed.')


# This object usually in chalicelib/app_utils.py
class AppUtils(AppUtils_from_cgap):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap-dbmi.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup is moved to vendor/ where it will be automatically placed at top level
    check_setup_dir = os.path.dirname(__file__)
    # This will heuristically mostly title-case te DEFAULT_ENV but will put CGAP in all-caps.
    # html_main_title = f'Foursight-{DEFAULT_ENV}'.title().replace("Cgap", "CGAP")  # was 'Foursight-CGAP-Mastertest'
    html_main_title = "Foursight" # Foursight CGAP vs Fourfront difference now conveyed in the upper left icon.
    DEFAULT_ENV = os.environ.get('ENV_NAME', 'foursight-cgap-env-uninitialized')


app_utils_obj = AppUtils.singleton(AppUtils)


######### SCHEDULED FUNCTIONS #########

def effectively_never():
    """Every February 31st, a.k.a. 'never'."""
    return Cron('0', '0', '31', '2', '?', '*')


def morning_10am_utc():
    """ Schedule for every morning at 10AM UTC (6AM EST) """
    return Cron('0', '10', '*', '*', '?', '*')


foursight_cron_by_schedule = {
    'prod': {
        'ten_min_checks': Cron('0/10', '*', '*', '*', '?', '*'),
        'fifteen_min_checks': Cron('0/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_2': Cron('5/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_3': Cron('10/15', '*', '*', '*', '?', '*'),
        'thirty_min_checks': Cron('0/30', '*', '*', '*', '?', '*'),
        'hourly_checks': Cron('0', '0/1', '*', '*', '?', '*'),
        'hourly_checks_2': Cron('15', '0/1', '*', '*', '?', '*'),
        'early_morning_checks': Cron('0', '8', '*', '*', '?', '*'),
        'morning_checks': Cron('0', '10', '*', '*', '?', '*'),
        'morning_checks_2': Cron('15', '10', '*', '*', '?', '*'),
        'evening_checks': Cron('0', '22', '*', '*', '?', '*'),
        'monday_checks': Cron('0', '9', '?', '*', '2', '*'),
        'monthly_checks': Cron('0', '9', '1', '*', '?', '*'),
        'manual_checks': effectively_never(),
    },
    'dev': {
        'ten_min_checks': Cron('5/10', '*', '*', '*', '?', '*'),
        'fifteen_min_checks': Cron('0/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_2': Cron('5/15', '*', '*', '*', '?', '*'),
        'fifteen_min_checks_3': Cron('10/15', '*', '*', '*', '?', '*'),
        'thirty_min_checks': Cron('15/30', '*', '*', '*', '?', '*'),
        'hourly_checks': Cron('30', '0/1', '*', '*', '?', '*'),
        'hourly_checks_2': Cron('45', '0/1', '*', '*', '?', '*'),
        'early_morning_checks': Cron('0', '8', '*', '*', '?', '*'),
        'morning_checks': Cron('30', '10', '*', '*', '?', '*'),
        'morning_checks_2': Cron('45', '10', '*', '*', '?', '*'),
        'evening_checks': Cron('0', '22', '*', '*', '?', '*'),
        'monday_checks': Cron('30', '9', '?', '*', '2', '*'),
        'monthly_checks': Cron('30', '9', '1', '*', '?', '*'),
        'manual_checks': effectively_never(),
    }
}

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


@app.schedule(foursight_cron_by_schedule[STAGE]['manual_checks'])
def manual_checks():
    app_utils_obj.queue_scheduled_checks('all', 'manual_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['morning_checks'])
def morning_checks(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'morning_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks'])
def fifteen_min_checks(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'fifteen_min_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks_2'])
def fifteen_min_checks_2(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'fifteen_min_checks_2')


@app.schedule(foursight_cron_by_schedule[STAGE]['fifteen_min_checks_3'])
def fifteen_min_checks_3(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'fifteen_min_checks_3')


@app.schedule(foursight_cron_by_schedule[STAGE]['hourly_checks'])
def hourly_checks(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'hourly_checks')


@app.schedule(foursight_cron_by_schedule[STAGE]['hourly_checks_2'])
def hourly_checks_2(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'hourly_checks_2')


@app.schedule(foursight_cron_by_schedule[STAGE]['monthly_checks'])
def monthly_checks(event):
    ignored(event)
    app_utils_obj.queue_scheduled_checks('all', 'monthly_checks')


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
    app_utils_obj.set_timeout(timeout)
