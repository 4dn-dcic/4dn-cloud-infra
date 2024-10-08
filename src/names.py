from dcicutils.cloudformation_utils import camelize
from dcicutils.exceptions import InvalidParameterError
from .c4name import C4Name
from .constants import (
    COMMON_STACK_PREFIX,
    COMMON_STACK_PREFIX_CAMEL_CASE,
    C4DatastoreBase,
    C4IAMBase,
    C4NetworkBase,
    C4SentieonSupportBase,
    C4AppConfigBase,
)
from .exports import C4DatastoreExportsMixin
from .mixins import StackNameBaseMixin


class Names(StackNameBaseMixin):

    # dmichaels/2022-06-06: Factored out from StackNameMixin.suggest_stack_name() in part.py.
    @staticmethod
    def suggest_stack_name(title_token, name_token, qualifier) -> C4Name:
        qualifier_suffix = f"-{qualifier}"
        qualifier_camel = camelize(qualifier)
        return C4Name(name=f'{COMMON_STACK_PREFIX}{name_token}{qualifier_suffix}',
                      title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{title_token}{qualifier_camel}'
                                   if title_token else None),
                      string_to_trim=qualifier_camel)

    # dmichaels/2022-07-14: Created to get datastore stack name.
    @classmethod
    def datastore_stack_name_object(cls, env_name: str) -> C4Name:
        title_token = C4DatastoreBase.STACK_TITLE_TOKEN
        name_token = C4DatastoreBase.STACK_NAME_TOKEN
        qualifier = env_name
        return cls.suggest_stack_name(title_token, name_token, qualifier)

    @classmethod
    def appconfig_stack_name_object(cls, env_name: str) -> C4Name:
        title_token = C4AppConfigBase.STACK_TITLE_TOKEN
        name_token = C4AppConfigBase.STACK_NAME_TOKEN
        qualifier = ''
        return cls.suggest_stack_name(title_token, name_token, qualifier)

    @classmethod
    def datastore_stack_name(cls, env_name: str) -> C4Name:
        return cls.datastore_stack_name_object(env_name).stack_name

    # dmichaels/2022-07-14: Created to get datastore stack output key name for the app files S3 bucket.
    @classmethod
    def datastore_stack_output_app_files_bucket_key(cls, env_name: str, c4name: C4Name = None) -> str:
        return cls.datastore_stack_name_object(env_name).logical_id(C4DatastoreExportsMixin.APPLICATION_FILES_BUCKET)

    # dmichaels/2022-07-14: Created to get datastore stack output key name for the app wfout S3 bucket.
    @classmethod
    def datastore_stack_output_app_wfout_bucket_key(cls, env_name: str, c4name: C4Name = None) -> str:
        return cls.datastore_stack_name_object(env_name).logical_id(C4DatastoreExportsMixin.APPLICATION_WFOUT_BUCKET)

    # dmichaels/2022-06-06: Factored out from C4Datastore.application_configuration_secret() in datastore.py.
    # XXX: Updated to reference the appconfig stack in newer versions - Will 27 Oct 2023
    @classmethod
    def application_configuration_secret(cls, env_name: str, c4name: C4Name = None) -> str:
        if not c4name:
            c4name = cls.appconfig_stack_name_object(env_name)
        return c4name.logical_id(camelize(env_name))

    # dmichaels/2022-06-20: Factored out from C4Datastore.rds_secret_logical_id() in datastore.py.
    @classmethod
    def rds_secret_logical_id(cls, env_name: str, c4name: C4Name = None) -> str:
        if not c4name:
            c4name = cls.datastore_stack_name_object(env_name)
        return c4name.logical_id(camelize(env_name) +
                                 C4DatastoreBase.RDS_SECRET_NAME_SUFFIX, context='rds_secret_logical_id')

    # dmichaels/2022-06-22: Factored out from C4IAM.suggest_sharing_qualifier() in part.py.
    @classmethod
    def suggest_sharing_qualifier(cls, sharing: str, env_name: str, ecosystem: str) -> str:
        sharing_qualifiers = cls.sharing_qualifiers(env_name=env_name, ecosystem=ecosystem)
        if sharing not in sharing_qualifiers:
            raise InvalidParameterError(parameter=f'{cls}.SHARING', value=sharing,
                                        options=list(sharing_qualifiers.keys()))
        return sharing_qualifiers[sharing]

    # dmichaels/2022-06-22: Factored out from C4IAM.ecs_s3_iam_user() in iam.py.
    @classmethod
    def ecs_s3_iam_user_logical_id(cls, c4name: C4Name = None, env_name: str = None, ecosystem: str = None) -> str:
        if not c4name:
            title_token = C4IAMBase.STACK_TITLE_TOKEN
            name_token = C4IAMBase.STACK_NAME_TOKEN
            qualifier = cls.suggest_sharing_qualifier(C4IAMBase.SHARING, env_name, ecosystem)
            c4name = cls.suggest_stack_name(title_token, name_token, qualifier)
        return c4name.logical_id('ApplicationS3Federator')

    # dmichaels/2022-07-05: Created to get Sentieon stack name; equivalent to
    # C4SentieonSupport.suggest_stack_name() but without importing sentieon.py which pulls in
    # base.py which is problematic for automation scripts (e.g. update-sentieon-security-groups).
    @classmethod
    def sentieon_stack_name_object(cls, env_name: str) -> C4Name:
        title_token = C4SentieonSupportBase.STACK_TITLE_TOKEN
        name_token = C4SentieonSupportBase.STACK_NAME_TOKEN
        qualifier = env_name
        return cls.suggest_stack_name(title_token, name_token, qualifier)

    @classmethod
    def sentieon_stack_name(cls, env_name: str) -> str:
        return cls.sentieon_stack_name_object(env_name).stack_name

    # dmichaels/2022-07-05: New to get stack output key name for Senteion server IP;
    # C4SentieonSupportExports.output_server_ip_key uses this common code.
    @classmethod
    def sentieon_output_server_ip_key(cls, env_name: str) -> str:
        return f"SentieonServerIP{camelize(env_name)}"

    # dmichaels/2022-07-06: Factored out from C4Network.application_security_group() in network.py.
    @classmethod
    def application_security_group_name(cls, c4name: C4Name = None) -> str:
        if not c4name:
            title_token = C4NetworkBase.STACK_TITLE_TOKEN  # Network (in constants.py, from C4Network.STACK_TITLE_TOKEN)
            name_token = C4NetworkBase.STACK_NAME_TOKEN    # network (in constants.py, from C4Network.STACK_NAME_TOKEN)
            qualifier = 'main'
            c4name = cls.suggest_stack_name(title_token, name_token, qualifier)
        return c4name.logical_id('ApplicationSecurityGroup', context='application_security_group')
