from dcicutils.cloudformation_utils import camelize, DEFAULT_ECOSYSTEM
from .c4name import C4Name
from .constants import COMMON_STACK_PREFIX, COMMON_STACK_PREFIX_CAMEL_CASE, Settings


# dmichaels/2022-07-08: Factored out from StackNameMixin in part.py.
class StackNameMixin:

    SHARING = 'env'
    def SHARING_QUALIFIERS(env_name: str, ecosystem: str):
        return {
            'env': f"{env_name}",
            'ecosystem': f"{ecosystem}",
            'account': "",
        }

    STACK_NAME_TOKEN = None
    STACK_TITLE_TOKEN = None
    STACK_TAGS = None

    @classmethod
    def stack_title_token(cls):
        return cls.STACK_TITLE_TOKEN or camelize(cls.STACK_NAME_TOKEN)

    @classmethod
    def suggest_sharing_qualifier(cls, sharing: str = None, env_name: str = None, ecosystem: str = None) -> str:
        if not sharing:
            sharing = cls.SHARING
        # N.B. This is a little wonky. Importing base.py from within conditionals in function by design,
        # so we do not import this from modules which do not need it, e.g. names.py, which is used by
        # pre-orchestration automation scripts, as importing base.py is problematic as it looks at the
        # ambient environment, which we do not want with such pre-orchestration automation scripts.
        # I.e. so any pre-orchestration automation scripts call this with env_name and ecosystem set.
        if not env_name:
            from .base import ConfigManager 
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        if not ecosystem:
            from .base import ConfigManager 
            ecosystem = ConfigManager.get_config_setting(Settings.S3_BUCKET_ECOSYSTEM, default=DEFAULT_ECOSYSTEM)
        sharing_qualifiers = cls.SHARING_QUALIFIERS(env_name, ecosystem)
        if sharing not in sharing_qualifiers:
            raise InvalidParameterError(parameter=f'{cls}.SHARING', value=sharing,
                                        options=list(sharing_qualifiers.keys()))
        return sharing_qualifiers[sharing]

    @classmethod
    def suggest_stack_name(cls, name: str = None, title_token: str = None, name_token: str = None, qualifier: str = None) -> C4Name:
        # N.B. The name argument became unused on 2022-05-17 (commit: 2e8e403).
        if not title_token:
            title_token = cls.stack_title_token()
        if not name_token:
            name_token = cls.STACK_NAME_TOKEN
        if not qualifier:
            qualifier = cls.suggest_sharing_qualifier()
        qualifier_suffix = f"-{qualifier}"
        qualifier_camel = camelize(qualifier)
        return C4Name(name=f'{COMMON_STACK_PREFIX}{name_token}{qualifier_suffix}',
                      title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{title_token}{qualifier_camel}'
                                   if title_token else None),
                      string_to_trim=qualifier_camel)


class SharedEnvStackNameMixin(StackNameMixin):
    SHARING = 'env'


class SharedEcosystemStackNameMixin(StackNameMixin):
    SHARING = 'ecosystem'


class SharedAccountStackNameMixin(StackNameMixin):
    SHARING = 'account'
