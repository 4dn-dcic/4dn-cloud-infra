import boto3
import contextlib
import os
from dcicutils.misc_utils import PRINT
from .misc_utils import obfuscate


class AwsContext:
    """
    Class to setup the context for AWS credentials which do NOT rely on environment AT ALL.
    I.e. neither on the AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables,
    nor on the ~/.aws credentials and config files (nor on the AWS_SHARED_CREDENTIALS_FILE
    and AWS_CONFIG_FILE environment variables).

    A specific path to the ~/.aws credentials directory MUST be specified, which will
    setup the context to refer to the credentials and config file(s) there; OR, specific
    AWS access key ID and associated secret access key (and default region) values MUST
    be specified; the latter taking precedence over the former. Usage like this:

        aws = AwsContext(your_aws_credentials_directory_or_access_key_id_and_secret_access_key)
        with aws.establish_credentials() as credentials:
            do_something_with_boto3()
            # if desired reference/use credentials values ...
            aws_access_key_id = credentials.access_key_id
            aws_secret_access_key = credentials.secret_access_key
            aws_default_region = credentials.default_region
            aws_account_number = credentials.account_number
            aws_user_arn = credentials.user_arn
    """

    def __init__(self,
                 aws_credentials_dir: str,
                 aws_access_key_id: str = None, aws_secret_access_key: str = None, aws_default_region: str = None,
                 aws_session_token: str = None):
        """
        Constructor which stores the given AWS credentials directory, and AWS access key ID
        and secret access key (and default region) for use when establishing AWS credentials.
        The latter takes precedence.

        :param aws_credentials_dir: Path to AWS credentials directory.
        :param aws_access_key_id: AWS credentials access key ID.
        :param aws_secret_access_key: AWS credentials secret access key.
        :param aws_default_region: AWS credentials default region.
        """
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_default_region = aws_default_region
        self._aws_session_token = aws_session_token
        self._aws_credentials_dir = aws_credentials_dir
        self._reset_boto3_default_session = True

    class Credentials:
        def __init__(self,
                     access_key_id: str, secret_access_key: str, default_region: str,
                     account_number: str, user_arn: str):
            self.access_key_id = access_key_id
            self.secret_access_key = secret_access_key
            self.default_region = default_region
            self.account_number = account_number
            self.user_arn = user_arn

    @contextlib.contextmanager
    def establish_credentials(self, display: bool = False, show: bool = False):
        """
        Context manager to establish AWS credentials without using environment,
        rather using the explicit AWS credentials directory or the explicit
        credentials values passed to the constructor of this object.

        Implementation note: to do this we temporarily (for the life of the context
        manager context) blow away the pertinent AWS credentials related environment
        variables, and set them appropriately based on given credentials information.

        :param display: If True then print summary of AWS credentials.
        :param show: If True and display True show in plaintext sensitive info for AWS credentials summary.
        :return: Yields named tuple with: access_key_id, secret_access_key, default_region, account_number, user_arn.
        """

        # TODO: Should we require all credentials, INCLUDING region, to come from EITHER
        # given arguments (i.e. command-line, ultimately) XOR from given AWS credentials
        # directory? I.e. so as not to split between them which may create some confusion.

        def unset_environ(environment_variables: list) -> dict:
            saved_environ = {}
            for environment_variable in environment_variables:
                saved_environ[environment_variable] = os.environ.pop(environment_variable, None)
                if environment_variable.endswith("_FILE"):
                    os.environ[environment_variable] = "/dev/null"
            return saved_environ

        def restore_environ(saved_environ: dict) -> None:
            for saved_environ_key, saved_environ_value in saved_environ.items():
                if saved_environ_value is not None:
                    os.environ[saved_environ_key] = saved_environ_value
                else:
                    os.environ.pop(saved_environ_key, None)

        # Temporarily (for the life of this context) unset/delete (here) and
        # override (below) any AWS credentials related environment variables.
        saved_environ = unset_environ(["AWS_ACCESS_KEY_ID",
                                       "AWS_CONFIG_FILE",
                                       "AWS_DEFAULT_REGION",
                                       "AWS_REGION",
                                       "AWS_SECRET_ACCESS_KEY",
                                       "AWS_SESSION_TOKEN",
                                       "AWS_SHARED_CREDENTIALS_FILE"])

        # This reset of the boto3.DEFAULT_SESSION is to workaround an odd problem with boto3
        # caching a default session, even for bad or non-existent credentials. This problem
        # was exhibited when importing (ultimately) modules from dcicutils (e.g. env_utils)
        # which (ultimately) globally creates a boto3 session with no credentials in effect.
        # Then our boto3 usage failed (here) with AWS credentials environment variables set.
        # Doing this just once (per AwsContext object creation) so as not to totally
        # undermine the (probably beneficial) caching that boto3 is trying to do.
        #
        # Ref: https://stackoverflow.com/questions/36894947/boto3-uses-old-credentials
        # Ref: https://github.com/boto/boto3/issues/1574
        if self._reset_boto3_default_session:
            boto3.DEFAULT_SESSION = None
            self._reset_boto3_default_session = False
        try:
            # Setup AWS environment variables for our specified credentials.
            if self._aws_access_key_id and self._aws_secret_access_key:
                os.environ["AWS_ACCESS_KEY_ID"] = self._aws_access_key_id
                os.environ["AWS_SECRET_ACCESS_KEY"] = self._aws_secret_access_key
            elif self._aws_session_token:
                os.environ["AWS_SESSION_TOKEN"] = self._aws_session_token
            elif self._aws_credentials_dir:
                aws_credentials_dir = self._aws_credentials_dir
                aws_credentials_file = os.path.join(aws_credentials_dir, "credentials")
                if os.path.isfile(aws_credentials_file):
                    os.environ["AWS_SHARED_CREDENTIALS_FILE"] = aws_credentials_file
                else:
                    raise Exception(f"AWS credentials directory not found: {aws_credentials_dir}")
                if display:
                    aws_credentials_dir_symlink_target = \
                        os.readlink(aws_credentials_dir) if os.path.islink(aws_credentials_dir) else None
                    if aws_credentials_dir_symlink_target:
                        PRINT(f"Your AWS credentials directory (link): {aws_credentials_dir}@ ->")
                        PRINT(f"Your AWS credentials directory (real): {aws_credentials_dir_symlink_target}")
                    else:
                        PRINT(f"Your AWS credentials directory: {aws_credentials_dir}")
            else:
                raise Exception(f"No AWS credentials specified.")
            if self._aws_default_region:
                os.environ["AWS_DEFAULT_REGION"] = self._aws_default_region
            else:
                aws_config_file = os.path.join(self._aws_credentials_dir, "config")
                if os.path.isfile(aws_config_file):
                    os.environ["AWS_CONFIG_FILE"] = aws_config_file

            # Setup AWS boto3 session/client to get basic AWS credentials info;
            session = boto3.session.Session()
            session_credentials = session.get_credentials()
            caller_identity = boto3.client("sts").get_caller_identity()

            credentials = AwsContext.Credentials(session_credentials.access_key,
                                                 session_credentials.secret_key,
                                                 session.region_name,
                                                 caller_identity["Account"],
                                                 caller_identity["Arn"])
            if display:
                PRINT(f"Your AWS account number: {credentials.account_number}")
                PRINT(f"Your AWS access key: {credentials.access_key_id}")
                PRINT(f"Your AWS access secret: {obfuscate(credentials.secret_access_key, show)}")
                PRINT(f"Your AWS default region: {credentials.default_region}")
                PRINT(f"Your AWS account user ARN: {credentials.user_arn}")

            # Yield pertinent AWS credentials info for caller in case they need/want them.
            yield credentials

        finally:
            # Restore any deleted/modified AWS credentials related environment variables.
            restore_environ(saved_environ)
