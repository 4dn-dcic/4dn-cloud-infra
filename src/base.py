import boto3
import io
import json
import os

from contextlib import contextmanager
from dcicutils.misc_utils import (
    decorator, file_contents, find_association, find_associations, full_class_name, override_environ,
)
from .exceptions import CLIException
from .constants import ENV_NAME, S3_BUCKET_ORG, S3_ENCRYPT_KEY, DEPLOYING_IAM_USER


_MISSING = object()

REGISTERED_STACKS = {}

COMMON_STACK_PREFIX = "c4-"

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


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))  # Our parent dir


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
        env_name = ConfigManager.get_config_setting(ENV_NAME)
        org_name = ConfigManager.get_config_setting(S3_BUCKET_ORG, default=None)  # Result is allowed to be missing or empty if none desired.
        org_prefix = (org_name + "-") if org_name else ""
        org_or_env_name = org_name or env_name  # compatibility. original account didn't have an org, so used env_name
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

    # path to config file, top level by default (previously named CONFIGURATION)
    CONFIG_FILE = os.path.join(ROOT_DIR, 'config.json')

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
    def get_config_setting(cls, var, default=_MISSING):
        with cls.validate_and_source_configuration():
            # At some point, we can & should get rid of the use of os.environ
            # and just get this straight from the config.
            if default is _MISSING:
                return os.environ[var]
            else:
                return os.environ.get(var)

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

        # TODO: Should this be ENVS = 'foursight-{org_or_env_name}-envs' ?
        ENVS = 'foursight-{org_prefix}{env_name}-envs'
        RESULTS = 'foursight-{org_prefix}{env_name}-results'
        APPLICATION_VERSIONS ='foursight-{org_prefix}{env_name}-application-versions'

    CLOUDFORMATION = None

    @classmethod
    def _cloudformation(cls):
        if cls.CLOUDFORMATION is None:
            cls.CLOUDFORMATION = cloudformation = boto3.resource('cloudformation')
        return cls.CLOUDFORMATION

    @classmethod
    def get_stack_output(cls, stack, output_id):
        entry = find_association(stack.outputs or [], OutputKey=output_id)
        return entry['OutputValue']

    @classmethod
    def lookup_stack(cls, stack_id):
        return cls._cloudformation().Stack(stack_id)

    @classmethod
    def find_stack(cls, name_token):
        # If name_token is network, the name might be c4-network-trial-alpha-stack or c4-network-trial-stack
        # so we search by the prefix that is common. -kmp 19-Jul-2021
        prefix = f"{COMMON_STACK_PREFIX}{name_token}-"
        candidates = []
        for stack in cls._cloudformation().stacks.all():
            if prefix in stack.name:
                candidates.append(stack)
        [candidate] = candidates or [None]
        return candidate

    @classmethod
    def find_stack_outputs(cls, key_or_pred, value_only=False):
        results = {}
        for stack in cls._cloudformation().stacks.all():
            for found in find_associations(stack.outputs or [], OutputKey=key_or_pred):
                results[found['OutputKey']] = found['OutputValue']
        if value_only:
            return list(results.values())
        else:
            return results

    @classmethod
    def find_stack_output(cls, key_or_pred, value_only=False):
        results = cls.find_stack_outputs(key_or_pred, value_only=value_only)
        n = len(results)
        if n == 0:
            return None
        elif n == 1:
            return (results[0]  # in this case, result is a list, so take its first element
                    if value_only
                    else results)   # if not value-only, result is a dictionary, which is fine
        else:
            raise ValueError(f"Too many matches for {key_or_pred}: {results}")

    @classmethod
    def find_stack_resource(cls, stack_name_token, resource_logical_id, attr=None, default=None):
        """
        Looks up a resource or resource attribute in a given stack.

        This is intended to use our mechanisms for looking up a stack in spite of its complex name,
        and then returning a given resource or some attribute of it. For example:

          ConfigManager.find_stack_resource('foursight', 'CheckRunner', 'physical_resource_id')

        might find a stack named 'c4-foursight-trial-alpha-stack' and then would look up
        the physical_resource_id of its CheckRunner resource. Without the final argument, the
        resource itself is returned.

        The default is returned if the stack doesn't exist, the named resource doesn't exist,
        or (if a resource attribute is requested) no such attribute exists in the resource.
        """
        stack = cls.find_stack(stack_name_token)
        if not stack:
            return default
        for summary in stack.resource_summaries.all():
            if summary.logical_id == resource_logical_id:
                if attr is None:
                    return summary
                else:
                    return getattr(summary, attr, default)
        return default
