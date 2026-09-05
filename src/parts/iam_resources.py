"""Explicit, ecosystem-wide inventory for the shared ECS role and S3 federator.

Never infer this inventory from the environment currently being provisioned: the IAM
stack is shared, and doing so revokes the other environments on an ordinary update.
Only physical names are accepted; ARN construction remains account/region-local.
"""
import ast
import json
import re

from ..base import ConfigManager
from ..constants import Settings


RESOURCE_PATTERNS = {
    'buckets': r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]',
    'queues': r'[a-zA-Z0-9_-]{1,80}(?:\.fifo)?',
    'search_domains': r'[a-z][a-z0-9-]{2,27}',
    'repositories': r'[a-z0-9][a-z0-9._/-]*',
    'runtime_secrets': r'[a-zA-Z0-9/_+=.@-]+',
    'kms_keys': r'(?:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}|mrk-[a-f0-9]{32})',
}


def ecosystem_resources():
    """Read a JSON object (including ConfigManager's stringified Python representation).

    Missing/partial inventories fail closed. Empty kms_keys is an explicit bootstrap
    choice: datastore key policies grant the shared principals access to those keys;
    no account-wide KMS fallback is emitted. Other resource classes must be nonempty.
    """
    setting = Settings.IAM_ECOSYSTEM_RESOURCES
    raw = ConfigManager.get_config_setting(setting, default=None)
    message = (f'{setting} must contain the complete shared IAM resource inventory '
               '(buckets, queues, search_domains, repositories, runtime_secrets, kms_keys). '
               'Do not replace it with only the current environment; see docs/source/iam_inventory.rst.')
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            try:
                raw = ast.literal_eval(raw)
            except (ValueError, SyntaxError):
                raise ValueError(message) from None
    if not isinstance(raw, dict) or set(raw) != set(RESOURCE_PATTERNS):
        raise ValueError(message)
    result = {}
    for key, pattern in RESOURCE_PATTERNS.items():
        values = raw[key]
        if not isinstance(values, list) or (not values and key != 'kms_keys'):
            raise ValueError(f'{setting}.{key} must be a list of exact physical names. {message}')
        if any(not isinstance(value, str) or not re.fullmatch(pattern, value) for value in values):
            raise ValueError(f'{setting}.{key} requires exact physical names, not ARNs or wildcards')
        if key == 'runtime_secrets' and any(value.endswith(('FalconClientID', 'FalconClientSecret'))
                                            for value in values):
            raise ValueError(f'{setting}.runtime_secrets must not grant Falcon API build credentials to ECS')
        result[key] = sorted(set(values))
    return result
