# IN PROGRESS / dmichaels / 2022-06-04
#
# Module with miscellaneous utilities.
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

import io
import json
import os
import secrets 
import string 
from   dcicutils.misc_utils import json_leaf_subst as expand_json_template

def expand_json_template_file(template_file: str, output_file: str, template_substitutions: dict):
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

def generate_s3_encrypt_key():
    """
    Returns a value suitable for an S3 encryption key.
    We use the cryptographically secure Python 'secrets' module.
    See: https://docs.python.org/3/library/secrets.html
    """
    return secrets.token_urlsafe()

    # TODO - OLD
    # Replicating exactly the method used in scripts/create_s3_encrypt_key but
    # should we rather modify that script and call out to it? And if we do do
    # it here then may need to also replicate the openssl version checking.
    #
    # s3_encrypt_key_command = "openssl enc -aes-128-cbc -k `ps -ax | md5` -P -pbkdf2 -a"
    # s3_encrypt_key_command_output = subprocess.check_output(s3_encrypt_key_command, shell=True).decode("utf-8").strip()
    # return re.compile("key=(.*)\n").search(s3_encrypt_key_command_output).group(1)

def confirm_with_user(message: str):
    """
    Prompts the user with the given message and asks for yes or no.
    Returns True if 'yes' (exactly, case-insensitive) otherwise False.
    """
    input_answer = input(message + " (yes|no) ").strip().lower()
    if input_answer == "yes":
        return True
    return False

def exit_with_no_action(message: str = "", status: int = 1):
    if message:
        print(message)
    print("Exiting without doing anything.")
    exit(status)

def print_directory_tree(directory: str):
    """
    Prints the given directory as a tree. Taken/adapted from:
    https://stackoverflow.com/questions/9727673/list-directory-tree-structure-in-python
    """
    def tree_generator(directory, prefix: str = ''):
        space = '    ' ; branch = '│   ' ; tee = '├── ' ; last = '└── '
        contents = [os.path.join(directory, item) for item in sorted(os.listdir(directory))]
        pointers = [tee] * (len(contents) - 1) + [last]
        for pointer, path in zip(pointers, contents):
            symlink = "@ ─> " + os.readlink(path) if os.path.islink(path) else ""
            yield prefix + pointer + os.path.basename(path) + symlink
            if os.path.isdir(path):
                extension = branch if pointer == tee else space 
                yield from tree_generator(path, prefix=prefix+extension)
    print('└─ ' + directory)
    for line in tree_generator(directory, prefix='   '): print(line)
