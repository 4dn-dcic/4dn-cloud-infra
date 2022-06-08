# Module/class (AwsEnvInfo) to gather/dispense info about the ~/.aws_test directories.
# Most notable the current_env and available_envs properties.
#
# Testing notes:
# - External resources accesed by this module:
#   - filesystem via:
#     - glob.glob
#     - os.path.basename
#     - os.path.expanduser
#     - os.path.isdir
#     - os.path.islink
#     - os.readlink

import os
import glob
from .defs import InfraDirectories


class AwsEnvInfo:
    """
    Class to gather/dispense info about the ~/.aws_test directories
    ala use_test_creds, i.e. what AWS credentials enviroment is currently
    active (based on what ~/.aws_test is symlinked to), and the list
    of available environments (based on what ~/.aws_test.{ENV_NAME}
    directories actually exist).

    Looks for set of directories of the form ~/.aws_test.{ENV_NAME} where ENV_NAME can
    be anything; and the directory ~/.aws_test can by symlinked to any or none of them.

    The current_env property returns the ENV_NAME for the one currently symlinked
    to, if any. The available_envs property returns a list of available
    ENV_NAMEs each of the ~/.aws_test.{ENV_NAME} directories which actually exist.

    May pass constructor a base directory name other than ~/.aws_test if desired.
    """

    # We're probably going to change this default directory name ~/.aws_test
    # to something like ~/.aws_cgap or something; when we do we can change
    # this, and/or can pass this into the AwsEnvInfo constructor.

    _DEFAULT_AWS_DIR = InfraDirectories.AWS_DIR

    def __init__(self, aws_dir: str = None):
        if not aws_dir:
            aws_dir = AwsEnvInfo._DEFAULT_AWS_DIR

        # FYI: os.path.expanduser expands tilde (~) even on Windows.

        self._aws_dir = os.path.expanduser(aws_dir)

        # Though the ~/.aws_test directory itself does not need to exist,
        # let's check that it's the parent does exist, just to make sure
        # someone didn't pass in some kind of garbage.

        parent_of_aws_dir = os.path.dirname(self._aws_dir)
        if not os.path.isdir(parent_of_aws_dir):
            raise NotADirectoryError(f"Parent of the AWS base directory does not even exist: {parent_of_aws_dir}")

    def _get_dirs(self) -> list:
        """
        Returns the list of ~/.aws_test.{ENV_NAME} directories which actually exist.
        :return: The list of directories or empty list of none.
        """
        dirs = []
        for dirname in glob.glob(self._aws_dir + ".*"):
            if os.path.isdir(dirname):
                dirs.append(dirname)
        return dirs

    def _get_env_name_from_path(self, path: str) -> str:
        """
        Returns the ENV_NAME from the given ~/.aws_test.{ENV_NAME} path.
        :param path: The path from which to extract the ENV_NAME.
        :return: The environment name from the path.
        """
        if path:
            basename = os.path.basename(path)
            aws_dir_basename = os.path.basename(self._aws_dir)
            if basename.startswith(aws_dir_basename + "."):
                return basename[len(aws_dir_basename) + 1:]

    @property
    def dir(self) -> str:
        """
        Returns the full path to the ~/.aws_test (_aws_dir) directory (from constructor).
        :return: The path to the base AWS directory.
        """
        return self._aws_dir

    @property
    def available_envs(self) -> list:
        """
        Returns a list of available AWS environments based on directory
        names of the form ~/.aws_test.{ENV_NAME} that actually exist.
        :return: The list of available AWS environments or None if none found.
        """
        return [self._get_env_name_from_path(path) for path in self._get_dirs()]

    @property
    def current_env(self) -> str:
        """
        Returns current the AWS environment name as represented by the ENV_NAME portion of
        the actual ~/.aws_test.{ENV_NAME} symlink target of the ~/.aws_test directory itself.
        Returns None if not set.
        :return: The current AWS environment name as symlinked to by ~/.aws_test.
        """
        symlink_target = os.readlink(self._aws_dir) if os.path.islink(self._aws_dir) else None
        return self._get_env_name_from_path(symlink_target)

    def get_dir(self, env_name: str) -> str:
        """
        Returns a full directory path name of the form ~/.aws_test.{ENV_NAME}
        for the given :param:`env_name`. This directory does NOT have to exist.
        :param env_name: The AWS environment name.
        :return: The ~/.aws_test.ENV_NAMe for the given environment name.
        """
        if env_name:
            return self._aws_dir + "." + env_name
