import logging
import os
import sys

from chalicelib.package import PackageDeploy as PackageDeploy_from_app
from dcicutils.misc_utils import PRINT, full_class_name
from os.path import dirname
from troposphere import Template
from .parts.application_configuration_secrets import ApplicationConfigurationSecrets
from .base import ConfigManager
from .constants import Secrets, Settings
from .names import Names
from .part import C4Name, C4Tags, C4Account, C4Part, StackNameMixin
from .parts.datastore import C4DatastoreExports
from .parts.network import C4NetworkExports

# Version string identifies template capabilities. Ref:
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/format-version-structure.html
CLOUD_FORMATION_VERSION = '2010-09-09'


class BaseC4Stack:
    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):
        self.name = name
        self.tags = tags
        self.account = account
        self.description = description

    def __str__(self):
        return f'<Stack {self.name}>'

    @staticmethod
    def write_template_file(template_text, template_file):
        """ Helper method for writing out a template to a file """

        # Verify the template file's path exists, and create if it doesn't
        path, filename = os.path.split(template_file)
        if os.path.exists(path) is False:
            os.makedirs(path)

        with open(template_file, 'w', newline='') as file:
            file.write(template_text)


class C4Stack(BaseC4Stack):
    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account, parts: [C4Part]):
        self.parts = [Part(name=name, tags=tags, account=account) for Part in parts]
        self.template = self.build_template_from_parts(self.parts, description)
        super().__init__(description=description, name=name, tags=tags, account=account)

    @staticmethod
    def build_template_from_parts(parts: [C4Part], description) -> Template:
        """ Helper function for building a template from scratch using a list of parts and a description. """
        template = Template()
        template.set_version(CLOUD_FORMATION_VERSION)
        template.set_description(description)
        for p in parts:
            template = p.build_template(template)
        return template

    OWNER_READ_ONLY_PERMISSION = 0o600

    def print_template(self, stdout=False, remake=True):
        """ Helper method for generating and printing a YAML template.
            If remake is set to true, rebuilds the template. If stdout is set to true, prints to stdout.
            :return (template object, file path, file name)
        """
        if remake:
            self.template = self.build_template_from_parts(self.parts, self.description)
        try:
            current_yaml = self.template.to_yaml()
        except TypeError as e:
            PRINT('TypeError when generating template..did you pass an uninstantiated class method as a Ref?')
            raise e
        # path, template_file = self.name.version_name(template_text=current_yaml)
        template_file = self.name.version_name(template_text=current_yaml)
        # path = ConfigManager.RELATIVE_TEMPLATES_DIR + "/"
        if stdout:
            PRINT(current_yaml, file=sys.stdout)
        else:
            # full_template_path = ''.join([path, template_file])
            full_template_path = os.path.join(ConfigManager.templates_dir(), template_file)
            self.write_template_file(current_yaml, full_template_path)
            mode = self.OWNER_READ_ONLY_PERMISSION
            os.chmod(full_template_path, mode)
            msg = f'Wrote template to {full_template_path} (mode {mode:o})'  # was template_file
            PRINT(msg)
            logging.info(msg)
        return self.template, template_file  # was self.template, path, template_file


class BaseC4FoursightStack(BaseC4Stack, StackNameMixin):
    """ This abstract class exists so that later if we want to make separate fourfront and cgap foursight classes,
        we can type-discriminate on the abstract class.
    """

    def package_foursight_stack(self, args):
        class_name = full_class_name(self)
        raise NotImplementedError(f"{class_name} does not implement required method 'package_foursight_stack'.")


def get_trial_creds(env_name: str):
    # dmichaels/2022-06-08: Factored out of C4FoursightCGAPStack.__init__() and C4FoursightFourfrontStack.__init__().
    return {
        'S3_ENCRYPT_KEY': ConfigManager.get_config_secret(Secrets.S3_ENCRYPT_KEY),
        'CLIENT_ID': ConfigManager.get_config_secret(Secrets.AUTH0_CLIENT),
        'CLIENT_SECRET': ConfigManager.get_config_secret(Secrets.AUTH0_SECRET),
        'DEV_SECRET': '',  # Better not to set this. ConfigManager.get_config_secret(Secrets.ENCODED_SECRET),
        'ES_HOST': ConfigManager.get_config_setting(Settings.FOURSIGHT_ES_URL, default=None) or
                   ApplicationConfigurationSecrets.get_es_url() + ":443",
        'ENV_NAME': env_name,
        'RDS_NAME': ConfigManager.get_config_setting(Settings.RDS_NAME, default=None) or f"rds-{env_name}",
        'S3_ENCRYPT_KEY_ID': ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None)
    }


class C4FoursightCGAPStack(BaseC4FoursightStack):

    STACK_NAME_TOKEN = "foursight"
    STACK_TITLE_TOKEN = "Foursight"
    SHARING = 'env'

    NETWORK_EXPORTS = C4NetworkExports()

    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):

        with ConfigManager.validate_and_source_configuration():
            self.security_ids = C4NetworkExports.get_security_ids()
            self.subnet_ids = C4NetworkExports.get_subnet_ids()
            self.global_env_bucket = C4DatastoreExports.get_env_bucket()
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            self.trial_creds = get_trial_creds(env_name)
        super().__init__(description, name, tags, account)

    def package_foursight_stack(self, args):
        # # TODO (C4-691): foursight-core presently picks up the global bucket env as an environment variable.
        # #       We should fix it to pass the argument lexically instead, as shown below.
        # #       Meanwhile, too, we're transitioning the name of the variable (from GLOBAL_BUCKET_ENV
        # #       to GLOBAL_ENV_BUCKET), so we compatibly bind both variables just in case that
        # #       name change goes into effect first. -kmp 4-Aug-2021
        # # TODO (C4-692): foursight-core presently wants us to pass an 'args' argument (from 'argparser').
        # #       It should instead ask for all the various arguments it plans to look at.
        # with override_environ(GLOBAL_ENV_BUCKET=self.global_env_bucket, GLOBAL_BUCKET_ENV=self.global_env_bucket):
        # dmichaels/20220725: Pass in identity to build_config_and_package (C4-826) to identity-ize Foursight.
        if args.foursight_identity:
            identity = args.foursight_identity
        else:
            identity = Names.application_configuration_secret(ConfigManager.get_config_setting(Settings.ENV_NAME))
        PRINT(f"Using custom IDENTITY (via --foursight-identity) for Foursight deployment: {identity}")
        self.PackageDeploy.build_config_and_package(
            args,  # this should not be needed any more, but we didn't quite write the code that way
            identity=identity,
            stack_name=self.name.stack_name,
            merge_template=args.merge_template,
            output_file=args.output_file,
            stage=args.stage,
            trial=args.trial,
            global_env_bucket=self.global_env_bucket,
            security_ids=self.security_ids,
            subnet_ids=self.subnet_ids,
            trial_creds=self.trial_creds,
            # On first pass stack creation, this will use a check_runner named CheckRunner-PLACEHOLDER.
            # On the second attempt to create the stack, the physical resource ID will be used.
            check_runner=(ConfigManager.find_stack_resource(f'foursight-fourfront-{args.stage}', 'CheckRunner', 'physical_resource_id')
                          or "c4-foursight-fourfront-production-stac-CheckRunner-MW4VHuCIsDXc")
        )

    class PackageDeploy(PackageDeploy_from_app):

        CONFIG_BASE = PackageDeploy_from_app.CONFIG_BASE
        CONFIG_BASE['app_name'] = 'foursight-cgap'

        config_dir = dirname(dirname(__file__))
        PRINT(f"Config dir: {config_dir}")


class C4FoursightFourfrontStack(BaseC4FoursightStack):
    """ Foursight-fourfront specific class. Mostly identical to CGAP (for now). """

    STACK_NAME_TOKEN = "foursight"
    STACK_TITLE_TOKEN = "Foursight"
    SHARING = 'env'

    NETWORK_EXPORTS = C4NetworkExports()

    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):

        with ConfigManager.validate_and_source_configuration():
            self.security_ids = C4NetworkExports.get_security_ids()
            self.subnet_ids = C4NetworkExports.get_subnet_ids()
            self.global_env_bucket = C4DatastoreExports.get_env_bucket()
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            self.trial_creds = get_trial_creds(env_name)
        super().__init__(description, name, tags, account)

    def package_foursight_stack(self, args):
        # # TODO (C4-691): foursight-core presently picks up the global bucket env as an environment variable.
        # #       We should fix it to pass the argument lexically instead, as shown below.
        # #       Meanwhile, too, we're transitioning the name of the variable (from GLOBAL_BUCKET_ENV
        # #       to GLOBAL_ENV_BUCKET), so we compatibly bind both variables just in case that
        # #       name change goes into effect first. -kmp 4-Aug-2021
        # # TODO (C4-692): foursight-core presently wants us to pass an 'args' argument (from 'argparser').
        # #       It should instead ask for all the various arguments it plans to look at.
        # with override_environ(GLOBAL_ENV_BUCKET=self.global_env_bucket, GLOBAL_BUCKET_ENV=self.global_env_bucket):
        self.PackageDeploy.build_config_and_package(
            args,  # this should not be needed any more, but we didn't quite write the code that way
            merge_template=args.merge_template,
            output_file=args.output_file,
            stage=args.stage,
            trial=args.trial,
            global_env_bucket=self.global_env_bucket,
            security_ids=self.security_ids,
            subnet_ids=self.subnet_ids,
            trial_creds=self.trial_creds,
            # On first pass stack creation, this will use a check_runner named CheckRunner-PLACEHOLDER.
            # On the second attempt to create the stack, the physical resource ID will be used.
            check_runner=("c4-foursight-fourfront-production-stac-CheckRunner-MW4VHuCIsDXc")
        )

    class PackageDeploy(PackageDeploy_from_app):

        CONFIG_BASE = PackageDeploy_from_app.CONFIG_BASE
        CONFIG_BASE['app_name'] = 'foursight-fourfront'

        config_dir = dirname(dirname(__file__))
        PRINT(f"Config dir: {config_dir}")

