import os
import tempfile
from src.auto.init_custom_dir.awsenvinfo import AwsEnvInfo

# Tests for the AwsEnvInfo utility class used by the init-custom-dir script.


def test_awsenvinfo():

    with tempfile.TemporaryDirectory() as tmp_dir:

        aws_dir = os.path.join(tmp_dir, ".aws_test")
        env_dir_abc = os.path.join(tmp_dir, ".aws_test.your-env-abc")
        os.makedirs(env_dir_abc)
        env_dir_def = os.path.join(tmp_dir, ".aws_test.your-env-def")
        os.makedirs(env_dir_def)
        env_dir_ghi = os.path.join(tmp_dir, ".aws_test.your-env-ghi")
        os.makedirs(env_dir_ghi)

        awsenvinfo = AwsEnvInfo(aws_dir)

        # Assure the directory supplied is what AwsEnvInfo uses.

        assert awsenvinfo.dir == aws_dir

        # Check the available envs (each of the abc, def, ghi test cases/directories above).

        assert sorted(awsenvinfo.available_envs) == ['your-env-abc', 'your-env-def', 'your-env-ghi']

        # Current env not yet set, i.e. ~/..aws_test not symlinked to any specific directory.
        assert not awsenvinfo.current_env

        # Symlink ~/.aws_test to each of test cases and check current_env.

        os.symlink(env_dir_abc, aws_dir)
        assert awsenvinfo.current_env == "your-env-abc"

        os.unlink(aws_dir)
        os.symlink(env_dir_def, aws_dir)
        assert awsenvinfo.current_env == "your-env-def"

        os.unlink(aws_dir)
        os.symlink(env_dir_ghi, aws_dir)
        assert awsenvinfo.current_env == "your-env-ghi"

        # Make sure we construct the full path to the env dir correctly; does not have to exist.

        assert awsenvinfo.get_dir('foo-bar') == aws_dir + ".foo-bar"
