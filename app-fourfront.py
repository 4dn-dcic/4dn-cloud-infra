import os

from chalice import Chalice, Response, Cron
from chalicelib.app_utils import AppUtils as AppUtils_from_fourfront  # naming convention used in foursight
from foursight_core.app_utils import app
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import environ_bool, remove_suffix, ignored
from foursight_core.deploy import Deploy


##################################
# Foursight (Fourfront) App Config
##################################


STAGE = os.environ.get('chalice_stage', 'dev')
HOST = os.environ.get('ES_HOST', None)
DEFAULT_ENV = os.environ.get('ENV_NAME', 'fourfront-uninitialized')

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
class AppUtils(AppUtils_from_fourfront):
    # overwriting parent class
    prefix = FOURSIGHT_PREFIX
    FAVICON = 'https://cgap-dbmi.hms.harvard.edu/static/img/favicon-fs.ico'
    host = HOST
    package_name = 'chalicelib'
    # check_setup is moved to vendor/ where it will be automatically placed at top level
    check_setup_dir = os.path.dirname(__file__)
    # html_main_title = f'Foursight-{DEFAULT_ENV}-{STAGE}'.title()
    # html_main_title = 'Foursight-Fourfront';
    html_main_title = "Foursight" # Foursight CGAP vs Fourfront difference now conveyed in the upper left icon.


app_utils_obj = AppUtils.singleton(AppUtils)


######### SCHEDULED FUNCTIONS #########

def effectively_never():
    """Every February 31st, a.k.a. 'never'."""
    return Cron('0', '0', '31', '2', '?', '?')


def end_of_day_on_weekdays():
    """ Cron schedule that runs at 6pm EST (22:00 UTC) on weekdays. Used for deployments. """
    return Cron('0', '22', '?', '*', 'MON-FRI', '*')


def friday_at_8_pm_est():
    """ Creates a Cron schedule (in UTC) for Friday at 8pm EST """
    return Cron('0', '0', '?', '*', 'SAT', '*')  # 24 - 4 = 20 = 8PM


def monday_at_2_am_est():
    """ Creates a Cron schedule (in UTC) for every Monday at 2 AM EST """
    return Cron('0', '6', '?', '*', 'MON', '*')  # 6 - 4 = 2AM


# this dictionary defines the CRON schedules for the dev and prod foursight
# stagger them to reduce the load on Fourfront. Times are UTC
# info: https://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html
foursight_cron_by_schedule = {
    'ten_min_checks': Cron('0/10', '*', '*', '*', '?', '*'),
    'thirty_min_checks': Cron('0/30', '*', '*', '*', '?', '*'),
    'hourly_checks_1': Cron('5', '0/1', '*', '*', '?', '*'),
    'hourly_checks_2': Cron('25', '0/1', '*', '*', '?', '*'),
    'hourly_checks_3': Cron('45', '0/1', '*', '*', '?', '*'),
    'morning_checks_1': Cron('0', '6', '*', '*', '?', '*'),
    'morning_checks_2': Cron('0', '7', '*', '*', '?', '*'),
    'morning_checks_3': Cron('0', '8', '*', '*', '?', '*'),
    'morning_checks_4': Cron('0', '9', '*', '*', '?', '*'),
    'monday_checks': Cron('0', '10', '?', '*', '2', '*'),
    'monthly_checks': Cron('0', '10', '1', '*', '?', '*'),
    'friday_autoscaling_checks': friday_at_8_pm_est(),
    'monday_autoscaling_checks': monday_at_2_am_est(),
    'manual_checks': effectively_never(),
    'deployment_checks': end_of_day_on_weekdays()
}


@app.lambda_function()
def check_runner(event, context):
    """
    Pure lambda function to pull run and check information from SQS and run
    the checks. Self propogates. event is a dict of information passed into
    the lambda at invocation time.
    """
    print("XYZZY: checker_runner lambda called.")
    if not event:
        print("XYZZY: checker_runner lambda no event.")
        return
    print("XYZZY: checker_runner lambda no event.")
    print(event)
    print(context)
    app_utils_obj.run_check_runner(event)


@app.schedule(foursight_cron_by_schedule['ten_min_checks'])
def ten_min_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'ten_min_checks')


@app.schedule(foursight_cron_by_schedule['thirty_min_checks'])
def thirty_min_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'thirty_min_checks')


@app.schedule(foursight_cron_by_schedule['hourly_checks_1'])
def hourly_checks_1(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'hourly_checks_1')


@app.schedule(foursight_cron_by_schedule['hourly_checks_2'])
def hourly_checks_2(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'hourly_checks_2')


@app.schedule(foursight_cron_by_schedule['hourly_checks_3'])
def hourly_checks_3(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'hourly_checks_3')


@app.schedule(foursight_cron_by_schedule['morning_checks_1'])
def morning_checks_1(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'morning_checks_1')


@app.schedule(foursight_cron_by_schedule['morning_checks_2'])
def morning_checks_2(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'morning_checks_2')


@app.schedule(foursight_cron_by_schedule['morning_checks_3'])
def morning_checks_3(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'morning_checks_3')


@app.schedule(foursight_cron_by_schedule['morning_checks_4'])
def morning_checks_4(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'morning_checks_4')


@app.schedule(foursight_cron_by_schedule['monday_checks'])
def monday_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'monday_checks')


@app.schedule(foursight_cron_by_schedule['monthly_checks'])
def monthly_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'monthly_checks')


@app.schedule(foursight_cron_by_schedule['deployment_checks'])
def deployment_checks(event):
    if STAGE == 'dev':
        return  # do not schedule the deployment checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'deployment_checks')


@app.schedule(foursight_cron_by_schedule['friday_autoscaling_checks'])
def friday_autoscaling_checks(event):
    if STAGE == 'dev':
        return  # do not schedule autoscaling checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'friday_autoscaling_checks')


@app.schedule(foursight_cron_by_schedule['monday_autoscaling_checks'])
def monday_autoscaling_checks(event):
    if STAGE == 'dev':
        return  # do not schedule autoscaling checks on dev
    app_utils_obj.queue_scheduled_checks('all', 'monday_autoscaling_checks')


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
