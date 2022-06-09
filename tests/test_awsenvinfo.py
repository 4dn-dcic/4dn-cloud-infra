# IN PROGRESS: dmichaels/2022-06-08

import os
import tempfile
import unittest

# TODO
# What is proper way to import these ... surely not like this?

from src.auto.init_custom_dir.awsenvinfo import AwsEnvInfo


class TestAwsEnvInfo(unittest.TestCase):
    """
    Tests for the AwsEnvInfo utility class used by the init-custom-dir script.
    """

    def test_awsenvinfo(self):

        with tempfile.TemporaryDirectory() as tmp_dir:

            aws_dir = os.path.join(tmp_dir, ".aws_test")
            env_dir_abc = os.path.join(tmp_dir, ".aws_test.my-test-abc")
            os.makedirs(env_dir_abc)
            env_dir_def = os.path.join(tmp_dir, ".aws_test.my-test-def")
            os.makedirs(env_dir_def)
            env_dir_ghi = os.path.join(tmp_dir, ".aws_test.my-test-ghi")
            os.makedirs(env_dir_ghi)

            awsenvinfo = AwsEnvInfo(aws_dir)

            # Assure the directory supplied is what AwsEnvInfo uses.

            assert awsenvinfo.dir == aws_dir

            # Check the available envs (each of the abc, def, ghi test cases/directories above).

            assert sorted(awsenvinfo.available_envs) == ['my-test-abc', 'my-test-def', 'my-test-ghi']

            # Current env not yet set, i.e. ~/..aws_test not symlinked to any specific directory.
            assert not awsenvinfo.current_env

            # Symlink ~/.aws_test to each of test cases and check current_env.

            os.symlink(env_dir_abc, aws_dir)
            assert awsenvinfo.current_env == "my-test-abc"

            os.unlink(aws_dir)
            os.symlink(env_dir_def, aws_dir)
            assert awsenvinfo.current_env == "my-test-def"

            os.unlink(aws_dir)
            os.symlink(env_dir_ghi, aws_dir)
            assert awsenvinfo.current_env == "my-test-ghi"

            # Make sure we construct the full path to the env dir correctly; does not have to exist.

            assert awsenvinfo.get_dir('foo-bar') == aws_dir + ".foo-bar"
