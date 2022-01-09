import json
import pytest

from dcicutils.env_utils import PublicUrlParts
from dcicutils.misc_utils import override_environ
from unittest import mock
from ..base import ConfigManager
from ..commands import assure_global_env_bucket as assure_global_env_bucket_module
from ..commands.assure_global_env_bucket import (
    make_env_utils_config,
    parse_env_to_host_mapping,
    parse_public_url_mapping,
    parse_public_url_mappings,
)


p = PublicUrlParts

MOCKED_ORG = 'acme'
MOCKED_ENV_NAME = 'acme-foo'


@mock.patch.object(assure_global_env_bucket_module, "ENV_NAME", MOCKED_ENV_NAME)
@mock.patch.object(assure_global_env_bucket_module, "S3_BUCKET_ORG", MOCKED_ORG)
@mock.patch.object(assure_global_env_bucket_module, "S3_IS_ENCRYPTED", None)
def test_make_env_utils_config():

    with mock.patch.object(assure_global_env_bucket_module, "get_portal_url") as mock_get_portal_url:
        with mock.patch.object(assure_global_env_bucket_module, "get_foursight_url") as mock_get_foursight_url:
            with mock.patch.object(ConfigManager, "get_config_setting") as mock_settings:
                with override_environ(ENV_NAME=MOCKED_ENV_NAME, S3_BUCKET_ORG=MOCKED_ORG):

                    mocked_settings_values = {}

                    missing = object()

                    def mocked_settings(var, default=missing):
                        if var in mocked_settings_values:
                            return mocked_settings_values[var]
                        elif default is not missing:
                            return default
                        else:
                            raise NotImplementedError("Setting for mocked %s is missing" % var)

                    mock_settings.side_effect = mocked_settings

                    foursight_prefix = "https://xyzzy999foo.execute-api.us-east-1.amazonaws.com/api/view/"

                    def mocked_get_foursight_url(*, env_name):
                        return f"{foursight_prefix}{env_name}"

                    mock_get_portal_url.return_value = "https://something-1a2b3cd4e5.elb.amazonaws.com/"
                    mock_get_foursight_url.side_effect = mocked_get_foursight_url

                    config = make_env_utils_config()

                    print(f"Config created: {json.dumps(config, indent=2, default=str)}")

                    assert config == {
                        'dev_data_set_table': {'acme-foo': 'prod'},
                        'dev_env_domain_suffix': '.elb.amazonaws.com',
                        'foursight_url_prefix': foursight_prefix,
                        'full_env_prefix': '',
                        'hotseat_envs': [],
                        'indexer_env_name': 'acme-foo-indexer',
                        'is_legacy': False,
                        'orchestrated_app': 'cgap',
                        'prd_env_name': 'acme-foo',
                        'public_url_table': {},
                        'stg_env_name': None,
                        'test_envs': [],
                        'webprod_pseudo_env': 'acme-foo'
                    }

                    mocked_settings_values = {
                        'env_utils.foursight_url_prefix': 'https://foursight.acme.com/api/view/',
                        'env_utils.full_env_prefix': 'acme-',
                        'env_utils.hotseat_envs': 'acme-demotest,acme-livetest',
                        'env_utils.public_url_mappings': 'cgap=acme-prd=cgap.acme.com',
                        'env_utils.test_envs': 'acme-uitest, acme-devtest',
                    }

                    config = make_env_utils_config()

                    print(f"Config created: {json.dumps(config, indent=2, default=str)}")

                    assert config == {
                        'dev_data_set_table': {'acme-foo': 'prod'},
                        'dev_env_domain_suffix': '.elb.amazonaws.com',
                        'foursight_url_prefix': foursight_prefix,
                        'full_env_prefix': 'acme-',
                        'hotseat_envs': ['acme-demotest', 'acme-livetest'],
                        'indexer_env_name': 'acme-foo-indexer',
                        'is_legacy': False,
                        'orchestrated_app': 'cgap',
                        'prd_env_name': 'acme-foo',
                        'public_url_table': [{
                            'environment': 'acme-prd',
                            'name': 'cgap',
                            'url': 'https://cgap.acme.com',
                            'host': 'cgap.acme.com',
                        }],
                        'stg_env_name': None,
                        'test_envs': ['acme-uitest', 'acme-devtest'],
                        'webprod_pseudo_env': 'acme-foo'
                    }


def test_parse_public_url_mappings():

    assert parse_public_url_mappings("", full_env_prefix='acme-') == []

    assert parse_public_url_mappings(
        "cgap=prd=genetics.example.com,"
        "stg=staging.genetics.example.com,"
        "testing=pubtest=https://testing.genetics.example.com/,"
        "demo=pubdemo=demo.genetics.example.com",
        full_env_prefix="acme-") == [
        {
            p.NAME: 'cgap',
            p.URL: 'https://genetics.example.com',
            p.HOST: 'genetics.example.com',
            p.ENVIRONMENT: 'acme-prd',
        },
        {
            p.NAME: 'stg',
            p.URL: 'https://staging.genetics.example.com',
            p.HOST: 'staging.genetics.example.com',
            p.ENVIRONMENT: 'acme-stg',
        },
        {
            p.NAME: 'testing',
            p.URL: 'https://testing.genetics.example.com',
            p.HOST: 'testing.genetics.example.com',
            p.ENVIRONMENT: 'acme-pubtest',
        },
        {
            p.NAME: 'demo',
            p.URL: 'https://demo.genetics.example.com',
            p.HOST: 'demo.genetics.example.com',
            p.ENVIRONMENT: 'acme-pubdemo',
        },
    ]


def test_parse_public_url_mapping():

    with pytest.raises(ValueError):
        parse_public_url_mapping("", full_env_prefix='acme-', http_scheme='https')

    assert parse_public_url_mapping('x=some.example.com', full_env_prefix='acme-', http_scheme='https') == {
        p.NAME: 'x',
        p.ENVIRONMENT: 'acme-x',
        p.HOST: 'some.example.com',
        p.URL: 'https://some.example.com',
    }

    assert parse_public_url_mapping('x=devx=some.example.com', full_env_prefix='acme-', http_scheme='https') == {
        p.NAME: 'x',
        p.ENVIRONMENT: 'acme-devx',
        p.HOST: 'some.example.com',
        p.URL: 'https://some.example.com',
    }

    assert parse_public_url_mapping('x=devx=some.example.com', full_env_prefix=None, http_scheme='https') == {
        p.NAME: 'x',
        p.ENVIRONMENT: 'devx',
        p.HOST: 'some.example.com',
        p.URL: 'https://some.example.com',
    }

    assert parse_public_url_mapping('x=devx=http://some.example.com', full_env_prefix=None, http_scheme='https') == {
        p.NAME: 'x',
        p.ENVIRONMENT: 'devx',
        p.HOST: 'some.example.com',
        p.URL: 'http://some.example.com',
    }


def test_parse_env_to_host_mapping():

    assert parse_env_to_host_mapping("cgap=prd=genetics.example.com") == ('cgap', 'prd', 'genetics.example.com')
    assert parse_env_to_host_mapping("devtest=genetics.example.com") == ('devtest', 'devtest', 'genetics.example.com')

    with pytest.raises(ValueError):
        parse_env_to_host_mapping("")

    with pytest.raises(ValueError):
        parse_env_to_host_mapping("devtest")

    with pytest.raises(ValueError):
        parse_env_to_host_mapping("cgap=prd=garbage=foo.com")
