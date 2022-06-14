import os
import tempfile
from src.auto.init_custom_dir.aws_credentials_info import AwsCredentialsInfo

# Tests for the AwsCredentialsInfo utility class used by the init-custom-dir script.


def test_aws_credentials_info():

    with tempfile.TemporaryDirectory() as tmp_dir:

        aws_dir = os.path.join(tmp_dir, ".aws_test")
        aws_credentials_dir_abc = os.path.join(tmp_dir, ".aws_test.your-abc")
        os.makedirs(aws_credentials_dir_abc)
        aws_credentials_dir_def = os.path.join(tmp_dir, ".aws_test.your-def")
        os.makedirs(aws_credentials_dir_def)
        aws_credentials_dir_ghi = os.path.join(tmp_dir, ".aws_test.your-ghi")
        os.makedirs(aws_credentials_dir_ghi)

        aws_credentials_info = AwsCredentialsInfo(aws_dir)

        # Assure the directory supplied is what AwsCredentialsInfo uses.
        assert aws_credentials_info.dir == aws_dir

        # Check the available credentials names (each of the abc, def, ghi test cases/directories above).
        assert sorted(aws_credentials_info.available_credentials_names) == \
               ['your-abc', 'your-def', 'your-ghi']

        # Current AWS credentials name not yet set, i.e. ~/.aws_test not symlinked to any specific directory.
        assert not aws_credentials_info.selected_credentials_name

        # Symlink ~/.aws_test to each of test cases and check selected_credentials_name.
        os.symlink(aws_credentials_dir_abc, aws_dir)
        assert aws_credentials_info.selected_credentials_name == "your-abc"

        os.unlink(aws_dir)
        os.symlink(aws_credentials_dir_def, aws_dir)
        assert aws_credentials_info.selected_credentials_name == "your-def"

        os.unlink(aws_dir)
        os.symlink(aws_credentials_dir_ghi, aws_dir)
        assert aws_credentials_info.selected_credentials_name == "your-ghi"

        # Make sure we construct the full path to the AWS credentials dir correctly; does not have to exist.
        assert aws_credentials_info.get_credentials_dir('foo-bar') == aws_dir + ".foo-bar"
