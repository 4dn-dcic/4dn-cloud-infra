"""Exercise the deployment entrypoint offline; never execute an AppConfig change set."""
import logging
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.base import ConfigManager
from src.cli import C4Client


@pytest.mark.parametrize('probe_result,warns', [
    (subprocess.CompletedProcess([], 0, 'UPDATE_COMPLETE\n', ''), True),
    (subprocess.CompletedProcess([], 1, '', 'An error occurred (ValidationError): '
                                 'Stack with id c4-appconfig-smaht-test-stack does not exist'), False),
    (subprocess.CompletedProcess([], 1, '', 'AccessDenied'), True),
    (subprocess.CompletedProcess([], 1, '', 'ValidationError: another resource does not exist'), True),
    (OSError('docker unavailable'), True),
    (subprocess.TimeoutExpired(['docker'], 30), True),
])
def test_appconfig_warning_before_changeset(monkeypatch, synthesis_config, caplog, probe_result, warns):
    """Updates warn before upload; only a confirmed initial creation skips the warning."""
    synthesis_config('smaht')
    monkeypatch.setattr(ConfigManager, 'get_aws_creds_dir', lambda: '/offline/credentials with spaces')
    stack = SimpleNamespace(name=SimpleNamespace(stack_name='c4-appconfig-smaht-test-stack'))
    monkeypatch.setattr(C4Client, 'resolve_alpha_stack', lambda **kw: stack)
    monkeypatch.setattr(C4Client, 'resolve_4dn_stack', lambda **kw: None)
    monkeypatch.setattr(C4Client, 'write_and_validate_template', lambda **kw: '/offline/appconfig.json')
    probe = Mock(side_effect=probe_result) if isinstance(probe_result, Exception) else Mock(return_value=probe_result)
    monkeypatch.setattr(subprocess, 'run', probe)
    uploads = []

    def upload(command):
        # Assert visibility and order at the actual deployment boundary, not after return.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert bool(warnings) == warns
        if warns:
            message = warnings[0].getMessage()
            for text in ['WARNING', stack.name.stack_name, 'entire existing', 'Foursight',
                         'BREAK THE EXISTING PORTAL', 'DIRECTLY in Secrets Manager']:
                assert text in message
        uploads.append(command)

    monkeypatch.setattr(C4Client, 'run_command', upload)
    args = SimpleNamespace(stack='appconfig', upload_change_set=True, output_file=None,
                           stdout=False, validate=False, view_changes=False)
    with caplog.at_level(logging.WARNING):
        C4Client.provision_stack(args)
    assert len(uploads) == 1  # Warning-only, including when the read fails.
    assert '--no-execute-changeset' in uploads[0]
    assert '--stack-name c4-appconfig-smaht-test-stack' in uploads[0]
    assert probe.call_args.args[0] == [
        'docker', 'run', '--rm', '-v', '/offline/credentials with spaces:/root/.aws',
        'amazon/aws-cli', 'cloudformation', 'describe-stacks',
        '--stack-name', stack.name.stack_name, '--query', 'Stacks[0].StackStatus', '--output', 'text']
    assert probe.call_args.kwargs == {'capture_output': True, 'text': True, 'check': False, 'timeout': 30}


@pytest.mark.parametrize('target,upload_changes', [('appconfig', False), ('network', True)])
def test_no_warning_or_discovery_for_synthesis_or_other_stacks(
        monkeypatch, synthesis_config, caplog, target, upload_changes):
    stack = SimpleNamespace(name=SimpleNamespace(stack_name=f'c4-{target}-test-stack'))
    monkeypatch.setattr(C4Client, 'resolve_alpha_stack', lambda **kw: stack)
    monkeypatch.setattr(C4Client, 'resolve_4dn_stack', lambda **kw: None)
    monkeypatch.setattr(C4Client, 'write_and_validate_template', lambda **kw: '/offline/template.json')
    probe = Mock(side_effect=AssertionError('Unexpected stack discovery'))
    monkeypatch.setattr(subprocess, 'run', probe)
    monkeypatch.setattr(C4Client, 'run_command', Mock())
    args = SimpleNamespace(stack=target, upload_change_set=upload_changes, output_file=None,
                           stdout=False, validate=False, view_changes=False)
    C4Client.provision_stack(args)
    probe.assert_not_called()
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
