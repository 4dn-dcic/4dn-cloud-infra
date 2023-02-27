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
from .paths import MiscFiles
from typing import Callable, Optional
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
    except Exception:
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


def get_script_exported_variable(shell_script_file: str, env_variable_name: str) -> Optional[str]:
    """
    Obtains/returns the value of the given environment variable name by actually
    executing the given shell script file in a sub-shell.

    WARNING: Since the given full (bash) script file is actually executed, be very
             CAREFUL what you pass here; i.e. that it has no unwanted side-effects.

    :param shell_script_file: Shell script file to execute.
    :param env_variable_name: Environment variable name to read.
    :return: Value of given environment variable name from the executed given shell script or None.
    """
    try:
        if not os.path.isfile(shell_script_file):
            return None
        # If we don't do unset first it inherits from any current environment variable of the name.
        command = f"unset {env_variable_name} ; source {shell_script_file} ; echo ${env_variable_name}"
        result = subprocess.run(command, shell=True, encoding="utf-8", capture_output=True, executable="/bin/bash")
        if result.stderr or result.returncode != 0 or not result.stdout:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def generate_password() -> str:
    """
    Returns a reasonably secure password, by simply concatenating 5 random words from the system
    dictionary words file; or if that is not possible, then returns a random 32-character string.

    :return: Generated password.
    """
    password = None
    # Will suggests using a password from some (5) random words.
    if os.path.isfile(MiscFiles.DICTIONARY_WORDS_FILE):
        dictionary_words_file = MiscFiles.DICTIONARY_WORDS_FILE
    elif os.path.isfile(MiscFiles.ALTERNATE_DICTIONARY_WORDS_FILE):
        dictionary_words_file = MiscFiles.ALTERNATE_DICTIONARY_WORDS_FILE
    else:
        dictionary_words_file = None
    if dictionary_words_file:
        try:
            with io.open(dictionary_words_file) as dictionary_words_fp:
                words = [word.strip() for word in dictionary_words_fp]
                if len(words) > 10000:
                    password = " ".join(secrets.choice(words) for _ in range(5))
        except Exception:
            pass
    if not password:
        password = secrets.token_hex(16)
    return password


def generate_encryption_key(length: int = 32) -> str:
    """
    Generate a cryptographically secure encryption key suitable for AWS S3 (or other) encryption.
    By default, length will be 16 characters; if length less than 1 uses 1; if odd length then adds 1.
    Ref:
    https://cryptobook.nakov.com/symmetric-key-ciphers/aes-encrypt-decrypt-examples#password-to-key-derivation
    https://docs.python.org/3/library/secrets.html#recipes-and-best-practices
    https://en.wikipedia.org/wiki/PBKDF2

    :param length: Length of encryption key to return; default 16; if less than 2 uses 2; if odd then adds 1.
    :return: Globally unique cryptographically secure encryption key.
    """
    if length < 2:
        length = 2
    elif length % 2 != 0:
        length += 1
    password_salt = os.urandom(16)
    # Integer floor (//) division by two of length because read returns double the length of this argument value.
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

    :param key: Key name of some property which may or may not need to be obfuscated.
    :return: True if the given key name looks like it represents a sensitive value.
    """
    secret_key_names_regex = re.compile(
        r"""
        .*(
            secret   |
            secrt    |
            password |
            passwd   |
            crypt
        ).*
        """, re.VERBOSE | re.IGNORECASE)
    return secret_key_names_regex.match(key) is not None


def obfuscate(value: str, show: bool = False) -> str:
    """
    Obfuscates and returns the given string value.

    :param value: Value to obfuscate.
    :param show: If True then do not actually obfuscate rather return value in plaintext.
    :return: Obfuscated (or not if show) value or empty string if not a string or empty.
    """
    return value if show else len(value) * "*"


def get_exception_string(exception) -> str:
    return f"{exception.__class__.__name__}: {exception}"


def print_exception(exception) -> None:
    PRINT(get_exception_string(exception))


def print_warning(message: str) -> None:
    PRINT(f"WARNING: {message}")


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
    print_warning("Exiting mid-action!")
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
                message = get_exception_string(exception)
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
    first = "└─ "
    space = "    "
    branch = "│   "
    tee = "├── "
    last = "└── "

    # This function adapted from stackoverflow:
    # Ref: https://stackoverflow.com/questions/9727673/list-directory-tree-structure-in-python
    def tree_generator(dirname: str, prefix: str = ""):
        contents = [os.path.join(dirname, item) for item in sorted(os.listdir(dirname))]
        pointers = [tee] * (len(contents) - 1) + [last]
        for pointer, path in zip(pointers, contents):
            symlink = "@ -> " + os.readlink(path) if os.path.islink(path) else ""
            yield prefix + pointer + os.path.basename(path) + symlink
            if os.path.isdir(path):
                extension = branch if pointer == tee else space
                yield from tree_generator(path, prefix=prefix+extension)
    PRINT(first + directory)
    for line in tree_generator(directory, prefix="   "):
        PRINT(line)


def print_dictionary_as_table(header_name: str, header_value: str,
                              dictionary: dict, display_value: Callable, sort: bool = True) -> None:
    table = PrettyTable()
    table.field_names = [header_name, header_value]
    table.align[header_name] = "l"
    table.align[header_value] = "l"
    if not callable(display_value):
        display_value = lambda _, value: value
    for key_name, key_value in sorted(dictionary.items(), key=lambda item: item[0]) if sort else dictionary.items():
        table.add_row([key_name, display_value(key_name, key_value)])
    PRINT(table)
