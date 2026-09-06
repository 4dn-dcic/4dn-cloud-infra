"""Regression: a failed formatter/init/validator/linter must never produce a green parent."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

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
