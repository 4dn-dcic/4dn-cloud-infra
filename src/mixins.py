# This file contains constants mapping to the environment variables
# that contain the desired information. Setting any of these values
# in config.json will have the effect of setting the configuration
# option for the orchestration. The only options listed that are
# currently unavailable are: ES_MASTER_COUNT, ES_MASTER_TYPE

# dmichaels/2022-06-22: Factored out from StackNameMixin in part.py.
class StackNameBaseMixin:
    SHARING = 'env'
    def SHARING_QUALIFIERS(env_name: str, ecosystem: str):
        _SHARING_QUALIFIERS = {
            'env': f"{env_name}",
            'ecosystem': f"{ecosystem}",
            'account': "",
        }
        return _SHARING_QUALIFIERS
