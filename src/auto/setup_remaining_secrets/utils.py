from prettytable import PrettyTable
import re
from dcicutils.misc_utils import PRINT


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


def exit_with_no_action(*messages, status: int = 1) -> None:
    """
    Prints the given message (if any), and another message indicating
    no action was taken. Exits with the given status.

    :param messages: Zero or more messages to print before exit.
    :param status: Exit status code.
    """
    for message in messages:
        PRINT(message)
    PRINT("Exiting without doing anything.")
    exit(status)


def print_dictionary_as_table(header_name: str, header_value: str, dictionary: dict, display_value, sort: bool = True) -> None:
    table = PrettyTable()
    table.field_names = [header_name, header_value]
    table.align[header_name] = "l"
    table.align[header_value] = "l"
    if not callable(display_value):
        display_value = lambda key, value: value
    for key, value in sorted(dictionary.items(), key=lambda item: item[0]) if sort else dictionary.items():
        table.add_row([key, display_value(key, value)])
    print(table)
