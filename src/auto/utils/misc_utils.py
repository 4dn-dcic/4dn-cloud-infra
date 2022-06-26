# Miscellaneous utilities for automation scripts.

import binascii
import contextlib
import io
import json
import os
import pbkdf2
from prettytable import PrettyTable
import re
import secrets
import subprocess
from typing import Optional
from dcicutils.misc_utils import (json_leaf_subst as expand_json_template, PRINT)


def get_json_config_file_value(name: str, config_file: str, fallback: str = None) -> Optional[str]:
    """
    Reads and returns the value of the given name from the given JSON config file,
    where the JSON is assumed to be a simple object with keys/values.
    Return the given fallback if the value cannot be retrieved.

    :param name: Key name of the value to return from the given JSON config file.
    :param config_file: Full path of the JSON config file.
    :param fallback: Value to return if a value for the given name cannot be determined.
    :return: Named value from given JSON config file or given fallback.
    """
    try:
        with io.open(config_file, "r") as config_fp:
            config_json = json.load(config_fp)
            value = config_json.get(name)
            return value if value else fallback
    except:
        return fallback


def expand_json_template_file(template_file: str, output_file: str, template_substitutions: dict) -> None:
    """
    Expands the JSON template file specified by the given :param:`template_file`
    with the substitutions in the given :param:`template_substitutions`
    dictionary and writes to the given :param:`output_file`.

    :param template_file: Input JSON template file path name.
    :param output_file: Output file path name.
    :param template_substitutions: Dictionary of substitution keys/values.
    """
    with io.open(template_file, "r") as template_fp:
        template_file_json = json.load(template_fp)
    expanded_template_json = expand_json_template(template_file_json, template_substitutions)
    with io.open(output_file, "w") as output_fp:
        json.dump(expanded_template_json, output_fp, indent=2)
        output_fp.write("\n")


def read_env_variable_from_subshell(shell_script_file: str, env_variable_name: str) -> Optional[str]:
    """
    Obtains/returns the value of the given envrionment variable name by actually
    executing the given shell script file in a sub-shell; be careful what you pass here.

    :param shell_script_file: Shell script file to execute.
    :param env_variable_name: Environment variable name to read.
    :return: Value of given environment variable name from the executed given shell script or None.
    """
    try:
        if not os.path.isfile(shell_script_file):
            return None
        # If we don't do unset first it inherits from any current environment variable of the name.
        command = f"unset {env_variable_name} ; source {shell_script_file} ; echo ${env_variable_name}"
        command_output = str(subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT).decode("utf-8")).strip()
        return command_output
    except:
        return None


def generate_encryption_key(length: int = 16) -> str:
    """
    Generate a cryptographically secure encryption key suitable for AWS S3 (or other) encryption.
    By default length will be 16 characters; if length less then 1 uses 1; if odd length then adds 1.
    References:
    https://cryptobook.nakov.com/symmetric-key-ciphers/aes-encrypt-decrypt-examples#password-to-key-derivation
    https://docs.python.org/3/library/secrets.html#recipes-and-best-practices

    :param length: Length of encryption key to return; default 16; ; if less then 1 uses 1; if odd then adds 1.
    :return: Globally unique cryptographically secure encryption key.
    """
    system_words_dictionary_file = "/usr/share/dict/words"

    def generate_password() -> str:
        # Will suggests using a password from some (4) random words.
        if os.path.isfile(system_words_dictionary_file):
            try:
                with open(system_words_dictionary_file) as system_words_fp:
                    words = [word.strip() for word in system_words_fp]
                    password = "".join(secrets.choice(words) for _ in range(4))
            except:
                password = ""
        # As fallback for the words thing, and in any case, tack on a random token.
        return password + secrets.token_hex(16)
    if length < 1:
        length = 1
    if length % 2 != 0:
        length += 1
    password_salt = os.urandom(16)
    encryption_key = pbkdf2.PBKDF2(generate_password(), password_salt).read(length // 2)
    encryption_key = binascii.hexlify(encryption_key).decode("utf-8")
    return encryption_key


def should_obfuscate(key: str) -> bool:
    """
    Returns True if the given key looks like it represents a secret value.
    N.B.: Dumb implementation. Just sees if it contains "secret" or "password"
    or "crypt" some obvious variants (case-insensitive), i.e. whatever is
    in the secret_key_names_for_obfuscation list, which can be a regular
    expression. Add more to secret_key_names_for_obfuscation if/when needed.

    :param key: Key name of some property which may or may not need to be obfuscated..
    :return: True if the given key name looks like it represents a sensitive value.
    """
    secret_key_names_for_obfuscation = [
        ".*secret.*",
        ".*secrt.*",
        ".*password.*",
        ".*passwd.*",
        ".*crypt.*"
    ]
    secret_key_names_regex = map(lambda regex: re.compile(regex, re.IGNORECASE), secret_key_names_for_obfuscation)
    return any(regex.match(key) for regex in secret_key_names_regex)


def obfuscate(value: str, show: bool = False) -> str:
    """
    Obfuscates and returns the given string value.

    :param value: Value to obfuscate.
    :param show: If True then do not actually obfuscate rather return value in plaintext.
    :return: Obfuscated (or not if show) value or empty string if not a string or empty.
    """
    return value if show else len(value) * "*"


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


def exit_with_partial_action(*messages, status: int = 1) -> None:
    """
    Prints the given message (if any), and another message indicating
    actions were partially taken. Exits with the given status.

    :param messages: Zero or more messages to print before exit.
    :param status: Exit status code.
    """
    for message in messages:
        PRINT(message)
    PRINT("WARNING: Exiting mid-action!")
    exit(status)


@contextlib.contextmanager
def setup_and_action():
    """
    Context manager to catch (keyboard) interrupt for code which does (read-only)
    setup followed by (read-write) actions. Exits in either case, but prints
    warning if interrupt during the actions. Usage like this:

    with setup_and_action() as state:
        do_setup_here()
        state.note_action_start()
        do_actions_here()

    """
    class SetupActionState:
        def __init__(self):
            self.status = 'setup'

        def note_action_start(self) -> None:
            self.status = 'action'

        def note_interrupt(self, exception) -> None:
            if isinstance(exception, KeyboardInterrupt):
                message = "Interrupt!"
            else:
                message = "Exception! " + str(e)
            if self.status != 'setup':
                exit_with_partial_action("\n", message)
            else:
                exit_with_no_action("\n", message)
            exit(1)

    state = SetupActionState()
    try:
        try:
            yield state
        except KeyboardInterrupt as e:
            state.note_interrupt(e)
    except Exception as e:
        state.note_interrupt(e)


def print_directory_tree(directory: str) -> None:
    """
    Prints the given directory recursively as a tree structure (follows symlinks).

    :param directory: Directory name whose tree structure to print.
    """
    # This function adapted stackoverflow:
    # Ref: https://stackoverflow.com/questions/9727673/list-directory-tree-structure-in-python
    def tree_generator(dirname: str, prefix: str = ""):
        space = "    "
        branch = "│   "
        tee = "├── "
        last = "└── "
        contents = [os.path.join(dirname, item) for item in sorted(os.listdir(dirname))]
        pointers = [tee] * (len(contents) - 1) + [last]
        for pointer, path in zip(pointers, contents):
            symlink = "@ -> " + os.readlink(path) if os.path.islink(path) else ""
            yield prefix + pointer + os.path.basename(path) + symlink
            if os.path.isdir(path):
                extension = branch if pointer == tee else space
                yield from tree_generator(path, prefix=prefix+extension)
    PRINT("└─ " + directory)
    for line in tree_generator(directory, prefix="   "):
        PRINT(line)


def print_dictionary_as_table(header_name: str, header_value: str,
                              dictionary: dict, display_value: callable, sort: bool = True) -> None:
    table = PrettyTable()
    table.field_names = [header_name, header_value]
    table.align[header_name] = "l"
    table.align[header_value] = "l"
    if not callable(display_value):
        display_value = lambda _, value: value
    for key_name, key_value in sorted(dictionary.items(), key=lambda item: item[0]) if sort else dictionary.items():
        table.add_row([key_name, display_value(key_name, key_value)])
    PRINT(table)
