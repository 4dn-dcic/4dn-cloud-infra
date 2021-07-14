import io
import json
import os

from contextlib import contextmanager
from dcicutils.misc_utils import decorator, file_contents, full_class_name, override_environ
from .exceptions import CLIException
from .constants import ENV_NAME, S3_BUCKET_ORG, S3_ENCRYPT_KEY, DEPLOYING_IAM_USER


REGISTERED_STACKS = {}

STACK_KINDS = ['legacy', 'alpha']


@decorator()
def register_stack_creator(*, name, kind):
    if kind not in STACK_KINDS:
        raise SyntaxError("A stack kind must be one of %s." % " or ".join(STACK_KINDS))

    def register_stack_creation_function(fn):
        subregistry = REGISTERED_STACKS.get(kind)
        if not subregistry:
            REGISTERED_STACKS[kind] = subregistry = {}
        subregistry[name] = fn
        return fn

    return register_stack_creation_function


def lookup_stack_creator(name, kind, exact=False):
    if kind not in STACK_KINDS:
        raise ValueError("A stack kind must be one of %s." % " or ".join(STACK_KINDS))
    for stack_short_name, stack_creator in REGISTERED_STACKS[kind].items():
        if exact and name == stack_short_name:
            return stack_creator
        elif not exact and stack_short_name in name:
            return stack_creator
    raise CLIException("A %s stack %s %r was not found." % (kind, "called" if exact else "whose name contains", name))


class ConfigManager:

    # Singleton Pattern. All internal methods assume an instance. The class methods will assure the instance
    # and then jump to the corresponding method.

    SINGLETON = None

    @classmethod
    def singleton(cls):
        if cls.SINGLETON is None:
            cls.SINGLETON = cls()
        return cls.SINGLETON

    @classmethod
    def resolve_bucket_name(cls, bucket_template: str) -> str:
        return cls.singleton()._resolve_bucket_name(bucket_template)

    def _resolve_bucket_name(self, bucket_template: str) -> str:
        """
        Resolves a bucket_template into a bucket_name (presuming an appropriate os.environ).
        The ENCODED_BS_ENV and ENCODED_S3_BUCKET_ORG environment variables are expected to be in place at time of call.
        """
        # NOTE: In legacy CGAP, we'd want to be looking at S3_BUCKET_ENV, which did some backflips to address
        #       the naming for foursight (including uses of prod_bucket_env), so that webprod was still used
        #       even after we changed to blue/green, but unless we're trying to make this deployment procedure
        #       cover that special case, it should suffice (and use fewer environment variables) to only worry
        #       about ENV_NAME. -kmp 24-Jun-2021
        env_name = os.environ[ENV_NAME]
        org_name = os.environ.get(S3_BUCKET_ORG)  # Result is allowed to be missing or empty if none desired.
        org_prefix = (org_name + "-") if org_name else ""
        bucket_name = bucket_template.format(env_name=env_name, org_prefix=org_prefix)
        # print(bucket_template,"=>",bucket_name)
        return bucket_name

    def _get_config(self, *, creds_dir, config_file):
        """ Validates that required keys are in config.json and overrides the environ for the
            invocation of the infra build. Yields control once the environment has been
            adjusted, transferring back to the caller - see provision_stack.
        """
        if not os.path.exists(config_file):
            raise CLIException('Required configuration file not present! Write config.json')
        config = self._load_config(config_file)
        if 'S3_ENCRYPT_KEY' not in config:
            s3_key_file = os.path.join(creds_dir, "s3_encrypt_key.txt")
            s3_encrypt_key = file_contents(s3_key_file).strip('\n')
            config[S3_ENCRYPT_KEY] = s3_encrypt_key
        for required_key in [DEPLOYING_IAM_USER, ENV_NAME, S3_ENCRYPT_KEY]:
            if required_key not in config:
                raise CLIException('Required key in configuration file not present: %s' % required_key)
        return config

    def _load_config(self, filename):
        """
        Loads a .json file, casting all the resulting dictionary values to strings
        so they are suitable config file values.
        """
        with io.open(filename) as fp:
            config = json.load(fp)
            config = {k: str(v) for k, v in config.items()}
            return config

    CONFIG_FILE = 'config.json'  # path to config file, top level by default (previously named CONFIGURATION)

    @classmethod
    @contextmanager
    def validate_and_source_configuration(cls, *, creds_dir=None, config_file=None):
        singleton = cls.singleton()
        config = singleton._get_config(creds_dir=creds_dir or cls.get_creds_dir(),
                                       config_file=config_file or cls.CONFIG_FILE)
        with override_environ(**config):
            yield

    AWS_DEFAULT_TEST_CREDS_DIR_FILE = "~/.aws_test_creds_dir"
    AWS_DEFAULT_DEFAULT_TEST_CREDS_DIR = "~/.aws_test"

    @classmethod
    def compute_aws_default_test_creds_dir(cls):
        # For anyone who doesn't want to use ~/.aws_test, you can put the dir you want in ~/.aws_test_creds_dir
        # However, you might also want to see the use_test_creds command in the c4-scripts repository. -kmp 8-Jul-2021
        file = os.path.expanduser(cls.AWS_DEFAULT_TEST_CREDS_DIR_FILE)
        if os.path.exists(file):
            creds_dir = os.path.expanduser(file_contents(file).strip())
            if isinstance(creds_dir, str) and os.path.exists(creds_dir) and os.path.isdir(creds_dir):
                return creds_dir
        return os.path.expanduser(cls.AWS_DEFAULT_DEFAULT_TEST_CREDS_DIR)

    CREDS_DIR = None

    @classmethod
    def get_creds_dir(cls):
        """
        Returns the creds_dir we will use.
        To ensure consistency, once this is looked at, the value cannot be changed.
        """
        if cls.CREDS_DIR is None:
            raise RuntimeError(f"Cannot {full_class_name(cls)}.get_creds_dir() because .set_creds_dir() wasn't used.")
        return cls.CREDS_DIR

    @classmethod
    def set_creds_dir(cls, new_creds_dir):
        if cls.CREDS_DIR is None:
            cls.CREDS_DIR = new_creds_dir
        elif cls.CREDS_DIR != new_creds_dir:
            raise ValueError(f"Attempt to set_creds_dir to {new_creds_dir}, but it is already {cls.CREDS_DIR}.")
        else:
            pass  # Nothing to do, it's already been set.

    class AppBucketTemplate:

        BLOBS = 'application-{org_prefix}{env_name}-blobs'
        FILES = 'application-{org_prefix}{env_name}-files'
        WFOUT = 'application-{org_prefix}{env_name}-wfout'
        SYSTEM = 'application-{org_prefix}{env_name}-system'
        METADATA_BUNDLES = 'application-{org_prefix}{env_name}-metadata-bundles'
        TIBANNA_LOGS = 'application-{org_prefix}{env_name}-tibanna-logs'

    class FSBucketTemplate:

        ENVS = 'foursight-{org_prefix}{env_name}-envs'
        RESULTS = 'foursight-{org_prefix}{env_name}-results'
        APPLICATION_VERSIONS ='foursight-{org_prefix}{env_name}-application-versions'
