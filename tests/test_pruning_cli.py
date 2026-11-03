import argparse

import pytest

from src.pruning import (
    add_pruning_arguments,
    pruning_options_from_args,
    should_upload_after_pruning,
)


def parser():
    command = argparse.ArgumentParser()
    add_pruning_arguments(command)
    return command


def test_no_pruning_controls_preserves_default_contract():
    args = parser().parse_args([])
    assert pruning_options_from_args(args) is None


def test_explicit_controls_build_core_contract():
    args = parser().parse_args([
        '--prune-dry-run', '--prune-report', '--prune-variant', 'cgap',
    ])
    assert pruning_options_from_args(args) == {
        'dry_run': True,
        'report': True,
        'variant': 'cgap',
        'skip_prune': False,
    }


def test_no_prune_is_explicit_bypass():
    args = parser().parse_args(['--no-prune'])
    assert pruning_options_from_args(args) == {
        'dry_run': False,
        'report': False,
        'variant': None,
        'skip_prune': True,
    }


def test_dry_run_and_no_prune_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        parser().parse_args(['--prune-dry-run', '--no-prune'])


def test_dry_run_prevents_package_upload():
    assert should_upload_after_pruning(True, True) is False
    assert should_upload_after_pruning(True, False) is True
    assert should_upload_after_pruning(False, True) is False
