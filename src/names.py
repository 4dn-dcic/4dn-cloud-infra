from dcicutils.cloudformation_utils import camelize

from .c4name import C4Name
from .constants import (
    COMMON_STACK_PREFIX,
    COMMON_STACK_PREFIX_CAMEL_CASE,
    C4DatastoreBase
)


class Names:

    # dmichaels/2022-06-06: Factored out from StackNameMixin.suggest_stack_name() in part.py.
    @staticmethod
    def suggest_stack_name(title_token, name_token, qualifier):
        qualifier_suffix = f"-{qualifier}"
        qualifier_camel = camelize(qualifier)
        return C4Name(name=f'{COMMON_STACK_PREFIX}{name_token}{qualifier_suffix}',
                      title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{title_token}{qualifier_camel}'
                                   if title_token else None),
                      string_to_trim=qualifier_camel)

    # dmichaels/2022-06-06: Factored out from C4Datastore.application_configuration_secret() in datastore.py.
    @classmethod
    def application_configuration_secret(cls, env_name: str, c4name: C4Name = None) -> str:
        if not c4name:
            title_token = C4DatastoreBase.STACK_TITLE_TOKEN  # Datastore (in constants.py, from C4Datastore.STACK_TITLE_TOKEN)
            name_token = C4DatastoreBase.STACK_NAME_TOKEN    # datastore (in constants.py, from C4Datastore.STACK_NAME_TOKEN)
            qualifier = env_name
            c4name = cls.suggest_stack_name(title_token, name_token, qualifier)
        return c4name.logical_id(camelize(env_name) + C4DatastoreBase.APPLICATION_CONFIGURATION_SECRET_NAME_SUFFIX)
