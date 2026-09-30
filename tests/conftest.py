"""Offline synthesis fixtures; no account discovery or live service validation."""
import socket

import botocore.client
import pytest
from troposphere import Template

from src import base
from src.base import ConfigManager
from src.part import C4Account, C4Tags
from src.parts import appconfig, codebuild, datastore, datastore_slim, ecs_blue_green, logging


@pytest.fixture
def synthesis_config(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Synthesis tests must not contact a network or AWS API')

    monkeypatch.setattr(socket.socket, 'connect', deny)
    monkeypatch.setattr(botocore.client.BaseClient, '_make_api_call', deny)

    def configure(kind='cgap', deployment='standalone', extra=None):
        values = {
            'app.kind': kind, 'app.deploy': deployment, 'ENCODED_ENV_NAME': f'{kind}-test',
            'account_number': '123456789012', 'deploying_iam_user': 'arn:aws:iam::123456789012:user/test',
            'identity': 'C4AppConfigTest', 'blue.identity': 'C4AppConfigTestBlue',
            'green.identity': 'C4AppConfigTestGreen', 'GITHUB_PERSONAL_ACCESS_TOKEN': 'offline-test',
            'private.subnets': 'subnet-0aaaaaaaaaaaaaaa1,subnet-0aaaaaaaaaaaaaaa2',
            'public.subnets': 'subnet-0aaaaaaaaaaaaaaa3,subnet-0aaaaaaaaaaaaaaa4',
            'db.vpc.id': 'vpc-0bbbbbbbbbbbbbbb1', 'db.vpc.cidr': '10.20.0.0/16',
            'db.private.subnets': 'subnet-0bbbbbbbbbbbbbbb1,subnet-0bbbbbbbbbbbbbbb2',
            'compute.vpc.id': 'vpc-0ccccccccccccccc1', 'compute.vpc.cidr': '10.30.0.0/16',
            'compute.private.subnets': 'subnet-0ccccccccccccccc1,subnet-0ccccccccccccccc2',
            'fourfront.vpc': 'vpc-0aaaaaaaaaaaaaaa1', 'fourfront.vpc.cidr': '10.10.0.0/16',
            'fourfront.vpc.subnet_a': 'subnet-0aaaaaaaaaaaaaaa1',
            'fourfront.vpc.subnet_b': 'subnet-0aaaaaaaaaaaaaaa2',
            'fourfront.rds.sg': 'sg-0bbbbbbbbbbbbbbb1', 'fourfront.https.sg': 'sg-0aaaaaaaaaaaaaaa1',
            'crowdstrike.entrypoint': '["/vendor/loader", "/application-entrypoint"]',
        }
        values.update(extra or {})
        monkeypatch.setattr(ConfigManager.singleton(), '_CACHED_CONFIG',
                            {k: str(v) if v is not None else None for k, v in values.items()})
        # Production reads these after sourcing configuration at import time. Exercise each
        # combination without reloading modules (which would re-register all stack creators).
        for module in [base, appconfig, codebuild, datastore, datastore_slim, ecs_blue_green, logging]:
            if hasattr(module, 'APP_KIND'):
                monkeypatch.setattr(module, 'APP_KIND', kind)
            if hasattr(module, 'APP_DEPLOYMENT'):
                monkeypatch.setattr(module, 'APP_DEPLOYMENT', deployment)
        return values

    configure()
    return configure


@pytest.fixture
def synthesize():
    def build(cls):
        part = cls(name=cls.suggest_stack_name(), tags=C4Tags(),
                   account=C4Account(account_number='123456789012', creds_file='/dev/null'))
        return part.build_template(Template()).to_dict()
    return build
