# Module/class (AwsCredentialsInfo) to gather/dispense info about the ~/.aws_test directories.
# Most notable the selected_credentials_name and available_credentials_names properties.
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


class AwsCredentialsInfo:
    """
    Class to gather/dispense info about the ~/.aws_test directories, ala use_test_creds,
    i.e. what AWS credentials name is currently active (based on what ~/.aws_test
    is symlinked to), and the list of available credentials names (based on
    what ~/.aws_test.<aws-credentials-name> directories actually exist).

    Looks for set of directories of the form ~/.aws_test.<aws-credentials-name>
    where <aws-credentials-name> can be anything; and the directory ~/.aws_test
    can by symlinked to any or none of those.

    The selected_credentials_name property returns the <aws-credentials-name>
    for the one currently symlinked to, if any. The available_credentials_names
    property returns a list of available <aws-credentials-name>s for each of
    the ~/.aws_test.<aws-credentials-name> directories which actually exist.

    May pass constructor an AWS base directory name other than ~/.aws_test if desired.
    """

    # We're probably going to change this default directory name ~/.aws_test
    # to something like ~/.aws_cgap or something; when we do we can change
    # this, and/or can pass this into the AwsCredentialsInfo constructor.
    _DEFAULT_AWS_DIR = InfraDirectories.AWS_DIR

    def __init__(self, aws_dir: str = None) -> None:
        """
        :param aws_dir: Alternate base AWS directory; default from InfraDirectories.AWS_DIR.
        """
        if not aws_dir:
            aws_dir = AwsCredentialsInfo._DEFAULT_AWS_DIR

        # Make sure we didn't get pass, say, "~/.aws_test/" which would mess things up.
        aws_dir = aws_dir.rstrip("/")

        if not aws_dir:
            # Here, it means only slashes were given.
            # Odd state of affairs. Think it's okay to just default to the default.
            aws_dir = AwsCredentialsInfo._DEFAULT_AWS_DIR

        # FYI: os.path.expanduser expands tilde (~) even on Windows.
        self._aws_dir = os.path.expanduser(aws_dir)

        # Though the ~/.aws_test directory itself does not need to exist,
        # let's check that it's the parent does exist, just to make sure
        # someone didn't pass in some kind of garbage.
        parent_of_aws_dir = os.path.dirname(self._aws_dir)
        if not os.path.isdir(parent_of_aws_dir):
            raise NotADirectoryError(f"Parent of the AWS base directory does not even exist: {parent_of_aws_dir}")

    def _get_credentials_dirs(self) -> list:
        """
        Returns the list of ~/.aws_test.<aws-credentials-name> directories which actually exist.

        :return: List of directories or empty list of none.
        """
        dirs = []
        for path in glob.glob(f"{self._aws_dir}.*"):
            if os.path.isdir(path):
                dirs.append(path)
        return dirs

    def _get_credentials_names_from_dir(self, path: str) -> str:
        """
        Returns the <aws-credentials-name> from the given ~/.aws_test.<aws-credentials-name> path.

        :param path: Path from which to extract the <aws-credentials-name>.
        :return: AWS credentials name from the path.
        """
        if path:
            basename = os.path.basename(path)
            aws_dir_basename = os.path.basename(self._aws_dir)
            if basename.startswith(f"{aws_dir_basename}."):
                return basename[len(aws_dir_basename) + 1:]

    @property
    def dir(self) -> str:
        """
        Returns the full path to the ~/.aws_test (_aws_dir) directory (from constructor).

        :return: Full path to the base AWS directory.
        """
        return self._aws_dir

    @property
    def available_credentials_names(self) -> list:
        """
        Returns a list of available AWS AWS credentials names based on directory
        names of the form ~/.aws_test.<aws-credentials-name> that actually exist.

        :return: List of available AWS credentials names; empty list if none found.
        """
        return [self._get_credentials_names_from_dir(path) for path in self._get_credentials_dirs()]

    @property
    def selected_credentials_name(self) -> str:
        """
        Returns current the AWS credentials name as represented by the <aws-credentials-name> portion
        of the actual ~/.aws_test.<aws-credentials-name> symlink target of the ~/.aws_test directory itself.

        :return: Current AWS credentials name as symlinked to by ~/.aws_test or None.
        """
        symlink_target = os.readlink(self._aws_dir) if os.path.islink(self._aws_dir) else None
        return self._get_credentials_names_from_dir(symlink_target)

    def get_credentials_dir(self, aws_credentials_name: str) -> str:
        """
        Returns a full directory path name of the form ~/.aws_test.{aws-credentials-name}
        for the given :param:`aws_credentials_name`. This directory does NOT have to exist.

        :param aws_credentials_name: AWS credentials name.
        :return: Full directory path for given AWS credentials name (e.g. ~/.aws_test.{aws-credentials-name}).
        """
        if aws_credentials_name:
            return f"{self._aws_dir}.{aws_credentials_name}"
