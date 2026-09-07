"""Opt-in fail-closed test sandbox: PYTHONPATH=tests/offline:. python -m pytest.

No operator config/secret files are opened. Configuration reads receive synthetic JSON,
including before pytest fixtures load; network and botocore API boundaries are blocked.
This file is NOT on the production application's Python path.
"""

import builtins
import io
import json
import os
from pathlib import Path
import socket

ROOT = Path(__file__).resolve().parents[2]
CONFIG = {
    "app.kind": "cgap",
    "app.deploy": "standalone",
    "ENCODED_ENV_NAME": "cgap-test",
    "account_number": "123456789012",
    "deploying_iam_user": "arn:aws:iam::123456789012:user/test",
}
SECRETS = {
    "Auth0Client": "synthetic",
    "Auth0Secret": "synthetic",
    "S3_ENCRYPT_KEY": "synthetic",
    "GITHUB_PERSONAL_ACCESS_TOKEN": "synthetic",
}
_original_open, _original_io_open, _original_exists = builtins.open, io.open, os.path.exists


def safe_open(original):
    def open_file(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, bytes, os.PathLike)):
            path = os.path.abspath(os.fsdecode(file))
            if path.startswith(str(ROOT / "custom") + os.sep):
                if path in [str(ROOT / "custom/config.json"), str(ROOT / "custom/secrets.json")] and mode == "r":
                    return io.StringIO(json.dumps(CONFIG if path.endswith("config.json") else SECRETS))
                raise AssertionError("Offline tests cannot read/write operator custom files")
        return original(file, mode, *args, **kwargs)

    return open_file


builtins.open = safe_open(_original_open)
io.open = safe_open(_original_io_open)


def exists(path):
    absolute = os.path.abspath(path)
    if absolute in [str(ROOT / "custom/config.json"), str(ROOT / "custom/secrets.json")]:
        return True
    if absolute.startswith(str(ROOT / "custom") + os.sep):
        return False
    return _original_exists(path)


os.path.exists = exists
for key in list(os.environ):
    # ConfigManager falls back to os.environ for keys omitted from a fixture. Remove
    # inherited config AND credential names, not only AWS_* (before any app imports).
    if (
        key.startswith("AWS_")
        or "." in key
        or any(word in key.lower() for word in ["auth0", "secret", "token", "password", "recaptcha", "encrypt_key"])
    ):
        del os.environ[key]
os.environ.update(
    AWS_SHARED_CREDENTIALS_FILE="/dev/null",
    AWS_CONFIG_FILE="/dev/null",
    AWS_EC2_METADATA_DISABLED="true",
    AWS_DEFAULT_REGION="us-east-1",
    AWS_ACCESS_KEY_ID="synthetic",
    AWS_SECRET_ACCESS_KEY="synthetic",
)


def deny(*args, **kwargs):
    raise AssertionError("Offline tests must not contact a network or AWS API")


socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
import botocore.client  # noqa: E402

botocore.client.BaseClient._make_api_call = deny
