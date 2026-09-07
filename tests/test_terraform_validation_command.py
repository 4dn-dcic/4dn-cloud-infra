"""Regression: a failed formatter/init/validator/linter must never produce a green parent."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "failure,mode",
    [("fmt", "schema"), ("init", "schema"), ("validate", "schema"), ("lint", "lint"), ("none", "schema")],
)
def test_validation_child_exit_reporting(tmp_path, failure, mode):
    tools = tmp_path / "terraform/tools"
    tools.mkdir(parents=True)
    script = tools / "validate.sh"
    shutil.copy(ROOT / "terraform/tools/validate.sh", script)
    for folder in ["accounts/test/shared", "modules/test"]:
        directory = tmp_path / "terraform" / folder
        directory.mkdir(parents=True)
        (directory / "main.tf").write_text("")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    fake = """#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
# Check that credential and command-injection inputs have really been removed.
[ -z "${AWS_PROFILE:-}" ] && [ "$AWS_SHARED_CREDENTIALS_FILE" = /dev/null ] || exit 88
[ -z "${TF_CLI_ARGS:-}" ] && [ -z "${TF_VAR_secret:-}" ] || exit 89
case "$*" in *-it*|*--tty*) exit 90 ;; esac
case "$FAILURE:$*" in fmt:*fmt*|init:*init*|validate:*validate*|lint:*) exit 17 ;; esac
exit 0
"""
    for name in ["terraform", "tflint"]:
        binary = binaries / name
        binary.write_text(fake)
        binary.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        FAILURE=failure,
        CALL_LOG=str(tmp_path / "calls"),
        AWS_PROFILE="must-not-use",
        TF_VAR_secret="must-not-use",
        TF_CLI_ARGS="-input=true",
    )
    result = subprocess.run(
        ["bash", str(script), mode], cwd=tmp_path, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if failure == "none":
        assert result.returncode == 0 and "0 failed" in result.stdout
        assert "not deployment validation" in result.stdout
    else:
        assert result.returncode == 1
        assert "checks failed" in result.stdout
        assert "checks passed" not in result.stdout
        assert "failed:" in result.stdout
    calls = (tmp_path / "calls").read_text()
    if failure == "init":
        assert "validate" not in calls  # never validate a failed/uninitialized root
    if mode == "schema":
        assert "-backend=false -input=false" in calls
    assert not any(command in calls for command in [" apply ", " plan ", " import "])


def test_workflow_disables_terraform_output_wrapper():
    """Verbose mock plans belong to the parity harness, not GitHub's step-output file."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/terraform.yml").read_text())
    setup = next(
        step for step in workflow["jobs"]["fmt-validate"]["steps"]
        if step.get("uses", "").startswith("hashicorp/setup-terraform@")
    )
    assert setup["with"].get("terraform_wrapper") is False


@pytest.mark.parametrize("parent_exists", [False, True])
@pytest.mark.parametrize("child_fails", [False, True])
def test_workflow_pytest_temp_contract(tmp_path, parent_exists, child_fails):
    """Execute the real CI shell block with real pytest, without Poetry installs or Terraform."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/terraform.yml").read_text())
    step = next(
        step for step in workflow["jobs"]["fmt-validate"]["steps"] if "--basetemp=" in step.get("run", "")
    )
    assert step["env"] == {"PYTHONPATH": "tests/offline:.", "TF_PARITY": "1"}
    parent = tmp_path / ".parity"
    if parent_exists:
        parent.mkdir()
        (parent / "keep.txt").write_text("not pytest-owned")
        (parent / "pytest").mkdir()
        (parent / "pytest/stale.txt").write_text("old run")
    (tmp_path / "pytest.ini").write_text("[pytest]\n")
    (tmp_path / "test_temp.py").write_text(
        "def test_temp(tmp_path):\n"
        "    assert tmp_path.parent.name == 'pytest'\n"
        "    assert not (tmp_path.parent / 'stale.txt').exists()\n"
        f"    assert {not child_fails!r}, 'deliberate child failure'\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    poetry = binaries / "poetry"
    poetry.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "assert sys.argv[1:3] == ['run', 'pytest']\n"
        "os.execv(sys.executable, [sys.executable, '-m', 'pytest', *sys.argv[3:]])\n"
    )
    poetry.chmod(0o755)
    env = dict(
        os.environ,
        PATH=str(binaries) + os.pathsep + os.environ["PATH"],
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1",
        PYTEST_ADDOPTS="",
    )
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode == (1 if child_fails else 0), result.stdout
    assert ("1 failed" if child_fails else "1 passed") in result.stdout, result.stdout
    assert "FileNotFoundError" not in result.stdout
    if parent_exists:
        assert (parent / "keep.txt").read_text() == "not pytest-owned"
