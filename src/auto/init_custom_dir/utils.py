# Miscellaneous utilities.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - glob.glob
#     - io.open
#     - os.listdir
#     - os.path.basename
#     - os.path.isdir
#     - os.path.join
#     - os.readlink
#   - shell via:
#     - subprocess.check_output (to execute test_cred.sh)

import binascii
import contextlib
import io
import json
import os
import pbkdf2
import secrets
import subprocess
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import json_leaf_subst as expand_json_template
from dcicutils.misc_utils import PRINT
from .defs import InfraFiles


def expand_json_template_file(template_file: str, output_file: str, template_substitutions: dict) -> None:
    """
    Expands the JSON template file specified by the given :param:`template_file`
    with the substitutions in the given :param:`template_substitutions`
    dictionary and writes to the given :param:`output_file`.
    :param template_file: The input JSON template file path name.
    :param output_file: The output file path name.
    :param template_substitutions: The dictionary of substitution keys/values.
    """
    with io.open(template_file, "r") as template_f:
        template_file_json = json.load(template_f)
    expanded_template_json = expand_json_template(template_file_json, template_substitutions)
    with io.open(output_file, "w") as output_f:
        json.dump(expanded_template_json, output_f, indent=2)
        output_f.write("\n")


def generate_s3_encrypt_key() -> str:
    """
    Generate a cryptographically secure encryption key suitable for AWS S3 encryption.
    References:
    https://cryptobook.nakov.com/symmetric-key-ciphers/aes-encrypt-decrypt-examples#password-to-key-derivation
    https://docs.python.org/3/library/secrets.html#recipes-and-best-practices
    :return: Cryptographically secure encryption key.
    """
    def generate_password() -> str:
        # Will suggests using a password from some (4) random words.
        password = ""
        if os.path.isfile(InfraFiles.SYSTEM_WORDS_DICTIONARY_FILE):
            try:
                with open(InfraFiles.SYSTEM_WORDS_DICTIONARY_FILE) as system_words_f:
                    words = [word.strip() for word in system_words_f]
                    password = "".join(secrets.choice(words) for _ in range(4))
            except (Exception,) as _:
                pass
        # As fallback for the words thing, and in any case, tack on a random token.
        return password + secrets.token_hex(16)
    password_salt = os.urandom(16)
    s3_encrypt_key = pbkdf2.PBKDF2(generate_password(), password_salt).read(16)
    s3_encrypt_key = binascii.hexlify(s3_encrypt_key).decode("utf-8")
    return s3_encrypt_key


def read_env_variable_from_subshell(shell_script_file: str, env_variable_name: str) -> Optional[str]:
    """
    Obtains/returns the value of the given envrionment variable name by actually
    executing the given shell script file in a sub-shell; be careful what you pass here.
    :param shell_script_file: The shell script file to execute.
    :param env_variable_name: The environment variable name.
    :return: The value of the given environment variable name from the executed given shell script or None.
    """
    try:
        if not os.path.isfile(shell_script_file):
            return None
        command = f"unset {env_variable_name} ; source {shell_script_file} ; echo ${env_variable_name}"
        command_output = str(subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT).decode("utf-8")).strip()
        return command_output
    except (Exception,) as _:
        return None


def obfuscate(value: str) -> str:
    """
    Obfuscates and returns the given string value.
    :param value: The value to obfuscate.
    :return: The obfuscated value or empty string if not a string or empty.
    """
    return value[0] + "********" if isinstance(value, str) else ""


def confirm_with_user(message: str) -> bool:
    """
    Prompts the user with the given message and asks for yes or no.
    Returns True if "yes" (exactly, trimmed, case-insensitive) otherwise False.
    :param message: Message to print for the user prompt.
    :return: True if the user answers "yes" otherwise False.
    """
    return yes_or_no(message)


def exit_with_no_action(message: str = "", status: int = 1) -> None:
    """
    Prints the given message (if any), and another message indicating
    no action was taken. Exits with the given status.
    :param message: Message to print before exit.
    :param status: The exit status code.
    """
    if message:
        PRINT(message)
    PRINT("Exiting without doing anything.")
    exit(status)


def exit_with_partial_action(message: str = "", status: int = 1) -> None:
    """
    Prints the given message (if any), and another message indicating
    actions were partially taken. Exits with the given status.
    :param message: Message to print before exit.
    :param status: The exit status code.
    :param message: Message to print before exit.
    :param status: The exit status code.
    """
    if message:
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
    class ActionState:
        def __init__(self):
            self.status = 'setup'

        def note_action_start(self):
            self.status = 'action'

        def note_interrupt(self, exception):
            if isinstance(exception, KeyboardInterrupt):
                PRINT(f"\nInterrupt!")
            else:
                PRINT(f"\nException!")
            if self.status != 'setup':
                exit_with_partial_action()
            else:
                exit_with_no_action()
            exit(1)

    state = ActionState()
    try:
        try:
            yield state
        except KeyboardInterrupt as e:
            state.note_interrupt(e)
    except (Exception,) as e:
        state.note_interrupt(e)


def print_directory_tree(directory: str) -> None:
    """
    Prints the given directory as a tree structure.
    :param directory: The directory name whose tree structure to print.
    """
    # This function taken/adapted from:
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
