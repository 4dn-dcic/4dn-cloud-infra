import chalice
import os
import pytest

from dcicutils.misc_utils import override_environ

with override_environ(
    FOURSIGHT_PREFIX='just-for-testing-',
    ENV_NAME='just-for-testing-some-env',
    ES_HOST='just-for-testing-some-es-host',
):
    import app as app_module


def test_compute_valid_deploy_stages():

    valid_stages = app_module.compute_valid_deploy_stages()

    assert 'dev' in valid_stages
    assert 'prod' in valid_stages
    assert 'test' in valid_stages


def test_invalid_deploy_stage():

    e = app_module.InvalidDeployStage(parameter='stage', value='stg')
    assert str(e) == "The value of stage, 'stg', was not valid. Valid values are 'dev', 'prod' and 'test'."


def test_effectively_never():

    cron = app_module.effectively_never()
    # Every Feb 31 (=> never)
    assert isinstance(cron, chalice.app.Cron)
    assert cron.minutes == '0'
    assert cron.hours == '0'
    assert cron.day_of_month == '31'
    assert cron.month == '2'
    assert cron.day_of_week == '?'
    assert cron.year == '*'


def test_morning_10am_utc():

    cron = app_module.morning_10am_utc()
    assert isinstance(cron, chalice.app.Cron)
    assert cron.minutes == '0'
    assert cron.hours == '10'
    assert cron.day_of_month == '*'
    assert cron.month == '*'
    assert cron.day_of_week == '?'
    assert cron.year == '*'


def test_app_event_sources():

    assert set([source.name for source in app_module.app.event_sources]) == {
        'manual_checks',
        'morning_checks',
        'fifteen_min_checks',
        'fifteen_min_checks_2',
        'fifteen_min_checks_3',
        'hourly_checks',
        'hourly_checks_2',
    }


def test_set_stage():

    INITIALLY_INVALID_STAGE = "invalid-stage"  # not a valid value, but distinctive

    with override_environ(chalice_stage=INITIALLY_INVALID_STAGE):

        assert os.environ.get('chalice_stage') == INITIALLY_INVALID_STAGE

        with pytest.raises(app_module.InvalidDeployStage):
            app_module.set_stage(INITIALLY_INVALID_STAGE)  # setting it the real way would not work

        app_module.set_stage('dev')

        assert os.environ.get('chalice_stage') == 'dev'
