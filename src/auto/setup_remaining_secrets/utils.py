import re


def should_obfuscate(key: str) -> bool:
    """
    Returns True if the given key looks like it represents a secret value.
    N.B.: Dumb implementation. Just sees if it contains "secret" or "password"
    or "crypt" some obvious variants (case-insensitive), i.e. whatever is
    in the SECRET_KEY_NAMES_FOR_OBFUSCATION list, which can be a regular
    expression. Add more to SECRET_KEY_NAMES_FOR_OBFUSCATION if/when needed.
    """
    SECRET_KEY_NAMES_FOR_OBFUSCATION = [
        ".*secret.*",
        ".*secrt.*",
        ".*password.*",
        ".*passwd.*",
        ".*crypt.*"
    ]
    secret_key_names_regex = map(lambda regex: re.compile(regex, re.IGNORECASE), SECRET_KEY_NAMES_FOR_OBFUSCATION)
    return any(regex.match(key) for regex in secret_key_names_regex)


def obfuscate(value: str) -> str:
    """
    Obfuscates and returns the given string value.

    :param value: Value to obfuscate.
    :return: Obfuscated value or empty string if not a string or empty.
    """
    # return value[0] + "*******" if isinstance(value, str) else "********"
    return len(value) * "*"
