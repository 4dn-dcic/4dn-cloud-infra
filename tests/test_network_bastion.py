"""
Regression test for SEC-3: the bastion host in the standard network stack must be opt-in and
config-driven. A config that does not enable it (e.g. CI's mock config) must NOT crash and must
NOT emit a bastion; enabling it requires an explicit AMI and SSH key.
"""
from unittest import mock

from src.parts import network as network_mod
from src.parts.network import C4Network
from src.constants import Settings
from src.c4name import C4Name
from src.part import C4Tags, C4Account


def _make_network_part():
    name = C4Name('c4-network-main', title_token='C4NetworkMain')
    return C4Network(name=name, tags=C4Tags(),
                     account=C4Account(account_number='123456789', creds_file='/dev/null'))


def _config(settings):
    def _get(key, default=None):
        return settings.get(key, default)
    return _get


def test_bastion_skipped_when_not_enabled():
    part = _make_network_part()
    with mock.patch.object(network_mod.ConfigManager, 'get_config_setting', _config({})):
        assert part.bastion_host() is None


def test_bastion_skipped_when_enabled_but_missing_ami_or_key():
    part = _make_network_part()
    with mock.patch.object(network_mod.ConfigManager, 'get_config_setting',
                           _config({Settings.BASTION_ENABLED: True})):
        # enabled but no AMI/key -> skip rather than raise
        assert part.bastion_host() is None


def test_bastion_created_when_fully_configured():
    part = _make_network_part()
    settings = {
        Settings.BASTION_ENABLED: True,
        Settings.BASTION_AMI: 'ami-abc123',
        Settings.BASTION_SSH_KEY: 'my-admin-key',
    }
    with mock.patch.object(network_mod.ConfigManager, 'get_config_setting', _config(settings)):
        bastion = part.bastion_host()
    assert bastion is not None
    d = bastion.to_dict()['Properties']
    assert d['ImageId'] == 'ami-abc123'
    assert d['KeyName'] == 'my-admin-key'
