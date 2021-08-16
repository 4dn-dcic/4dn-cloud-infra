import boto3
import io
import json
import os
import re

from contextlib import contextmanager
from dcicutils.exceptions import InvalidParameterError
from dcicutils.lang_utils import conjoined_list
from dcicutils.misc_utils import (
    PRINT, check_true, decorator, file_contents, find_association, find_associations, ignorable, override_environ,
    snake_case_to_camel_case,
)
from .exceptions import CLIException
from .constants import Secrets, Settings


_MISSING = object()

REGISTERED_STACKS = {}
REGISTERED_STACK_CLASSES = {}

# Since Fourfront and CGAP are not intended to be in the same account, having different security requirements,
# we use the prefix C4 which is intended as the union of those two things.
COMMON_STACK_PREFIX = "c4-"
COMMON_STACK_PREFIX_CAMEL_CASE = "C4"

STACK_KINDS = ['alpha']  # No longer supporting 'legacy' stacks


def camelize(name):  # when this is debugged, this name can go away and tests can be simplified
    return snake_case_to_camel_case(name, separator='-')
    # return ''.join([i.capitalize() for i in name.split('-')])


def dehyphenate(name):
    return name.replace('-', '')


@decorator()
def register_stack_creator(*, name, kind, implementation_class):
    registered_classes = REGISTERED_STACK_CLASSES.get(kind)
    if registered_classes is None:
        REGISTERED_STACK_CLASSES[kind] = registered_classes = {}
    registered_classes[name] = implementation_class
    print(f"Registered {kind} class {name} as {implementation_class}.")
    if kind not in STACK_KINDS:
        raise InvalidParameterError(parameter="kind", value=kind, options=STACK_KINDS)
    def register_stack_creation_function(fn):
        subregistry = REGISTERED_STACKS.get(kind)
        if not subregistry:
            REGISTERED_STACKS[kind] = subregistry = {}
        subregistry[name] = fn
        return fn

    return register_stack_creation_function


def registered_stack_class(name, *, kind):
    if not isinstance(name, str):
        return name
    try:
        return REGISTERED_STACK_CLASSES[kind][name]
    except Exception:
        raise ValueError(f"No {kind} class {name!r} has been defined.")


def lookup_stack_creator(name, kind, exact=False):
    if kind not in STACK_KINDS:
        raise InvalidParameterError(parameter="kind", value=kind, options=STACK_KINDS)

    for stack_short_name, stack_creator in REGISTERED_STACKS[kind].items():
        if exact and name == stack_short_name:
            return stack_creator
        elif not exact and stack_short_name in name:
            return stack_creator

    raise CLIException("A %s stack %s %r was not found." % (kind, "called" if exact else "whose name contains", name))


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))  # Our parent dir


class ConfigManager:

    RELATIVE_TEMPLATES_DIR = 'out/templates'

    @classmethod
    def templates_dir(cls, relative_to=None) -> str:
        if relative_to is None:
            relative_to = os.path.abspath(os.getcwd())
        templates_dir = os.path.join(relative_to, ConfigManager.RELATIVE_TEMPLATES_DIR)
        return templates_dir

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
        Resolves a bucket_template into a bucket_name (presumably an approriate config file).
        The ENCODED_BS_ENV and ENCODED_S3_BUCKET_ORG environment variables are expected to be in place at time of call.
        """
        ignorable(self)  # We might want to later use the fact that this is an instance method, so don't make it static.
        # NOTE: In legacy CGAP, we'd want to be looking at S3_BUCKET_ENV, which did some backflips to address
        #       the naming for foursight (including uses of prod_bucket_env), so that webprod was still used
        #       even after we changed to blue/green, but unless we're trying to make this deployment procedure
        #       cover that special case, it should suffice (and use fewer environment variables) to only worry
        #       about ENV_NAME. -kmp 24-Jun-2021
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        env_part = f"{env_name}-"
        # The org_name is allowed to be missing or empty if none desired.
        org_name = ConfigManager.get_config_setting(Settings.S3_BUCKET_ORG, default=None)
        org_part = f"{org_name}-" if org_name else ""
        ecosystem_name = ConfigManager.get_config_setting(Settings.S3_BUCKET_ECOSYSTEM, default="main")
        ecosystem_part = f"{ecosystem_name}-" if ecosystem_name else ""
        app_kind = ConfigManager.get_config_setting(Settings.APP_KIND)
        base_prefix = f"{app_kind}-{org_part}{ecosystem_part}"
        foursight_prefix = f"{base_prefix}foursight-"
        application_prefix = f"{base_prefix}application-"
        bucket_name = bucket_template.format(env_name=env_name,
                                             env_part=env_part,
                                             application_prefix=application_prefix,
                                             foursight_prefix=foursight_prefix,
                                             )
        # print(bucket_template,"=>",bucket_name)
        return bucket_name

    REQUIRED_CONFIGS = [Settings.ACCOUNT_NUMBER, Settings.DEPLOYING_IAM_USER, Settings.ENV_NAME]
    REQUIRED_SECRETS = [Secrets.AUTH0_CLIENT, Secrets.AUTH0_SECRET, Secrets.ENCODED_SECRET, Secrets.S3_ENCRYPT_KEY]

    _CACHED_CONFIG = None

    def _get_config(self):
        """ Validates that required keys are in config.json and overrides the environ for the
            invocation of the infra build. Yields control once the environment has been
            adjusted, transferring back to the caller - see provision_stack.
        """
        if self._CACHED_CONFIG is not None:
            return self._CACHED_CONFIG

        if not os.path.exists(self.CONFIG_FILE):
            raise CLIException(f'The required configuration file, {self.CONFIG_FILE}, is not present.')
        config = self._load_config(self.CONFIG_FILE)
        check_true(set(self.REQUIRED_CONFIGS) <= config.keys(),
                   f"The file {self.CONFIG_FILE} is expected to contain"
                   f" secrets {conjoined_list(self.REQUIRED_CONFIGS)}.")
        if not os.path.exists(self.SECRETS_FILE):
            raise CLIException(f'The required configuration file, {self.SECRETS_FILE}, is not present.')
        secrets = self._load_config(self.SECRETS_FILE)
        if not secrets.get(Secrets.S3_ENCRYPT_KEY):  # if missing or empty, try to default from file
            secrets[Secrets.S3_ENCRYPT_KEY] = ConfigManager.get_s3_encrypt_key_from_file()
        else:
            PRINT(f"WARNING: {Secrets.S3_ENCRYPT_KEY} is not in {self.SECRETS_FILE},"
                  f" and the file {self.S3_ENCRYPT_KEY_FILE} does not exist.")
        check_true(set(self.REQUIRED_SECRETS) <= secrets.keys(),
                   f"The file {self.SECRETS_FILE} is expected to contain"
                   f" secrets {conjoined_list(self.REQUIRED_SECRETS)}.")
        for k, v in secrets.items():
            if k in config and config[k] != v:
                raise RuntimeError(f"The key {k} occurs in both {self.CONFIG_FILE} and {self.SECRETS_FILE}.")
            config[k] = v

        self._CACHED_CONFIG = config
        return config

    @classmethod
    def _load_config(cls, filename):
        """
        Loads a .json file, casting all the resulting dictionary values to strings
        so they are suitable config file values.
        """
        with io.open(filename) as fp:
            config = json.load(fp)
            config = {k: str(v) for k, v in config.items()}
            return config

    # path to config files, top level by default (previously named CONFIGURATION)
    CONFIG_FILE = os.path.join(ROOT_DIR, 'custom', 'config.json')
    SECRETS_FILE = os.path.join(ROOT_DIR, 'custom', 'secrets.json')
    AWS_CREDS_DIR = os.path.join(ROOT_DIR, 'custom', 'aws_creds')    # It's OK to link to ~/.aws_test/ or some such.

    @classmethod
    def get_aws_creds_dir(cls):
        """
        Returns the creds_dir we will use.
        To ensure consistency, once this is looked at, the value cannot be changed.
        """
        caveat = ""
        effective_creds_dir = os.path.abspath(cls.AWS_CREDS_DIR)
        if cls.AWS_CREDS_DIR != effective_creds_dir:
            caveat = f" (=> {effective_creds_dir})"
        PRINT(f"Using creds dir {cls.AWS_CREDS_DIR}{caveat} ...")
        return cls.AWS_CREDS_DIR

    @classmethod
    @contextmanager
    def validate_and_source_configuration(cls):
        singleton = cls.singleton()
        config = singleton._get_config()
        with override_environ(**config):
            yield

    S3_ENCRYPT_KEY_FILE = os.path.join(ROOT_DIR, "custom/aws_creds/s3_encrypt_key.txt")

    @classmethod
    def get_s3_encrypt_key_from_file(cls):
        return file_contents(cls.S3_ENCRYPT_KEY_FILE).strip()

    @classmethod
    def get_config_secret(cls, var, default=_MISSING, use_default_if_empty=True):
        return cls.get_config_setting(var, default=default, use_default_if_empty=use_default_if_empty)

    @classmethod
    def get_config_setting(cls, var, default=_MISSING, use_default_if_empty=True):
        with cls.validate_and_source_configuration():
            # At some point, we can & should get rid of the use of os.environ
            # and just get this straight from the config.
            if default is _MISSING:
                return os.environ[var]
            else:
                # Note that this is different defaulting behavior than os.environ.get
                # We treat missing or empty as equivalent, and prefer the default in that case.
                # Use has_config_setting in the rare case of it being necessary to distinguish empty from missing.
                found = os.environ.get(var)
                if found:
                    return found
                elif found is None or (use_default_if_empty and found is ""):
                    return default
                else:  # some other false value than None or "", for example zero (0).
                    return found

    class GenericAppBucketTemplate:

        BLOBS = '{application_prefix}{env_part}blobs'
        FILES = '{application_prefix}{env_part}files'
        WFOUT = '{application_prefix}{env_part}wfout'
        SYSTEM = '{application_prefix}{env_part}system'
        METADATA_BUNDLES = '{application_prefix}{env_part}metadata-bundles'
        TIBANNA_LOGS = '{application_prefix}tibanna-logs'  # NOTE: Shared in ecosystem. No {env_part}

    class GenericFSBucketTemplate:

        ENVS = '{foursight_prefix}envs'  # NOTE: Shared in ecosystem. No {env_part}
        RESULTS = '{foursight_prefix}{env_part}results'
        APPLICATION_VERSIONS = '{foursight_prefix}{env_part}application-versions'

    class OriginalAppBucketTemplate:

        BLOBS = '{application_prefix}{env_part}blobs'
        FILES = '{application_prefix}{env_part}files'
        WFOUT = '{application_prefix}{env_part}wfout'
        SYSTEM = '{application_prefix}{env_part}system'
        METADATA_BUNDLES = '{application_prefix}{env_part}metadata-bundles'
        TIBANNA_LOGS = '{application_prefix}tibanna-logs'  # NOTE: Shared in ecosystem. No {env_part}

    class OriginalFSBucketTemplate:

        ENVS = '{foursight_prefix}envs'  # NOTE: Shared in ecosystem. No {env_part}
        RESULTS = '{foursight_prefix}{env_part}results'
        APPLICATION_VERSIONS = '{foursight_prefix}{env_part}application-versions'

    ORIGINAL_ACCOUNT_NUMBER = '645819926742'

    @classmethod
    def get_app_bucket_template(cls, kind):
        if ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER) == cls.ORIGINAL_ACCOUNT_NUMBER:
            return getattr(cls.OriginalAppBucketTemplate, kind)
        else:
            return getattr(cls.GenericAppBucketTemplate, kind)

    @classmethod
    def get_fs_bucket_template(cls, kind):
        if ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER) == cls.ORIGINAL_ACCOUNT_NUMBER:
            return getattr(cls.OriginalFSBucketTemplate, kind)
        else:
            return getattr(cls.GenericFSBucketTemplate, kind)

    CLOUDFORMATION = None

    @classmethod
    def _cloudformation(cls):
        if cls.CLOUDFORMATION is None:
            cls.CLOUDFORMATION = boto3.resource('cloudformation')
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


USE_SHORT_EXPORT_NAMES = True  # TODO: Remove when debugged


def exportify(name):
    return name if USE_SHORT_EXPORT_NAMES else f"Export{name}"


VALID_APP_KINDS = ['cgap', 'ff']

APP_KIND = ConfigManager.get_config_setting(Settings.APP_KIND)

if APP_KIND not in VALID_APP_KINDS:
    raise InvalidParameterError(parameter=Settings.APP_KIND, value=APP_KIND, options=VALID_APP_KINDS)

ENV_NAME = ConfigManager.get_config_setting(Settings.ENV_NAME)

if not ENV_NAME or not re.match("[a-z][a-z0-9-]*", ENV_NAME):
    raise ValueError(f"The value of {Settings.ENV_NAME} must begin with an alphabetic"
                     f" and only contain alphanumerics or hyphens.")

DEPLOYING_IAM_USER = ConfigManager.get_config_setting(Settings.DEPLOYING_IAM_USER)

if not DEPLOYING_IAM_USER:
    raise ValueError(f"A setting for {Settings.DEPLOYING_IAM_USER} is required.")

ECOSYSTEM = ConfigManager.get_config_setting(Settings.S3_BUCKET_ECOSYSTEM, default='main')
