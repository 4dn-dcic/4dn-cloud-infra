import copy
import logging
import os
import sys

# Do not need this PackageDeploy import from (now) chalicelib_cgap or chalicelib_fourfront
# as the only thing it's doing is what's being done here anyways. dmichaels/2022-10-31.
# from .chalicelib.package import PackageDeploy as PackageDeploy_from_app
from foursight_core.package import PackageDeploy as PackageDeploy_from_core
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
from .parts.appconfig import C4AppConfigExports
from .parts.srce_network import C4SRCENetworkExports

# Version string identifies template capabilities. Ref:
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/format-version-structure.html
CLOUD_FORMATION_VERSION = '2010-09-09'


def foursight_config_base(app_name):
    """ Per-subclass copy of the vendored chalice CONFIG_BASE for one Foursight variant.

        This must be a DEEP copy. ``dict(PackageDeploy_from_core.CONFIG_BASE, app_name=...)``
        copies only the top level, so every Foursight variant used to share one
        ``CONFIG_BASE['stages']`` dict -- and ``foursight_core.deploy.Deploy.build_config()``
        mutates that dict in place, writing ``security_group_ids`` / ``subnet_ids`` /
        ``environment_variables`` into it. Sharing it means the SRCE variant's Application-VPC
        networking would leak into the non-SRCE variants' chalice config (and vice versa) whenever
        more than one variant is constructed in a single process, which is exactly the cross-VPC
        divergence the SRCE Foursight stack is supposed to make impossible.
    """
    return dict(copy.deepcopy(PackageDeploy_from_core.CONFIG_BASE), app_name=app_name)


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

    @classmethod
    def suggest_stack_name(cls, name=None):
        """ Overriden so you can change the sharing qualifier by passing foursight.app_name in
            config.json - used to have multiple foursight deployments per account.
            ie: set "foursight.app_name": "development" --> stack name = 'c4-foursight-development-stack'
        """
        title_token = cls.stack_title_token()
        name_token = cls.STACK_NAME_TOKEN
        fs_app_name = ConfigManager.get_config_setting(Settings.FOURSIGHT_APP_NAME, default=None)
        if fs_app_name:
            qualifier = fs_app_name
        else:
            qualifier = cls.suggest_sharing_qualifier()
        return Names.suggest_stack_name(title_token, name_token, qualifier)


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
        # dmichaels/20220725: Pass in identity to build_config_and_package (C4-826) to identity-ize Foursight.
        if args.foursight_identity:
            identity = args.foursight_identity
            PRINT(f"Using custom IDENTITY (via --foursight-identity) for Foursight deployment: {identity}")
        else:
            identity = Names.application_configuration_secret(ConfigManager.get_config_setting(Settings.ENV_NAME))
            PRINT(f"Using IDENTITY for Foursight deployment: {identity}")
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
            trial_creds=self.trial_creds
            # No longer need to set check_runner as it is determined dynamically at runtime in Foursight. dmichaels/2022-11-01.
            # On first pass stack creation, this will use a check_runner named CheckRunner-PLACEHOLDER.
            # On the second attempt to create the stack, the physical resource ID will be used.
            #check_runner=(ConfigManager.find_stack_resource(f'foursight-fourfront-{args.stage}',
            #                                                'CheckRunner', 'physical_resource_id')
            #             or "c4-foursight-fourfront-production-stac-CheckRunner-MW4VHuCIsDXc")
        )

    class PackageDeploy(PackageDeploy_from_core):

        CONFIG_BASE = foursight_config_base('foursight-cgap')

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
        # dmichaels/2022-08-15: Added for C4-826.
        if args.foursight_identity:
            identity = args.foursight_identity
            PRINT(f"Using custom IDENTITY (via --foursight-identity) for FoursightFourfront deployment: {identity}")
        else:
            identity = Names.application_configuration_secret(ConfigManager.get_config_setting(Settings.ENV_NAME))
            PRINT(f"Using IDENTITY for FoursightFourfront deployment: {identity}")
        self.PackageDeploy.build_config_and_package(
            args,  # this should not be needed any more, but we didn't quite write the code that way
            # dmichaels/2022-08-15: Added next two lines for C4-826.
            identity=identity,
            stack_name=self.name.stack_name,
            merge_template=args.merge_template,
            output_file=args.output_file,
            stage=args.stage,
            trial=args.trial,
            global_env_bucket=self.global_env_bucket,
            security_ids=self.security_ids,
            subnet_ids=self.subnet_ids,
            trial_creds=self.trial_creds
            # No longer need to set check_runner as it is determined dynamically at runtime in Foursight. dmichaels/2022-11-01.
            # On first pass stack creation, this will use a check_runner named CheckRunner-PLACEHOLDER.
            # On the second attempt to create the stack, the physical resource ID will be used.
            # check_runner=(ConfigManager.get_config_setting(Settings.FOURSIGHT_CHECK_RUNNER))
        )

    class PackageDeploy(PackageDeploy_from_core):

        CONFIG_BASE = foursight_config_base('foursight-fourfront')

        config_dir = dirname(dirname(__file__))
        PRINT(f"Config dir: {config_dir}")


class C4FoursightSMAHTStack(C4FoursightCGAPStack):

    STACK_NAME_TOKEN = "foursight"
    STACK_TITLE_TOKEN = "Foursight"
    SHARING = 'env'

    NETWORK_EXPORTS = C4NetworkExports()

    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):

        with ConfigManager.validate_and_source_configuration():
            self.security_ids = C4NetworkExports.get_security_ids()
            self.subnet_ids = C4NetworkExports.get_subnet_ids()
            self.global_env_bucket = C4AppConfigExports.get_env_bucket()
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            self.trial_creds = get_trial_creds(env_name)
        super().__init__(description, name, tags, account)

    def package_foursight_stack(self, args):
        # dmichaels/20220725: Pass in identity to build_config_and_package (C4-826) to identity-ize Foursight.
        if args.foursight_identity:
            identity = args.foursight_identity
            PRINT(f"Using custom IDENTITY (via --foursight-identity) for Foursight deployment: {identity}")
        else:
            raise Exception('Must use --foursight-identity to deploy foursight-smaht')
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
            trial_creds=self.trial_creds
        )

    class PackageDeploy(PackageDeploy_from_core):

        CONFIG_BASE = foursight_config_base('foursight-smaht')

        config_dir = dirname(dirname(__file__))
        PRINT(f"Config dir: {config_dir}")


class C4FoursightSMAHTSRCEStack(C4FoursightSMAHTStack):
    """ Foursight-SMaHT variant for SRCE deployments. Uses the SRCE Application VPC stack
        (C4SRCENetworkExports) for VPC/subnet/security-group lookups, mirroring how
        C4SRCEECSApplication swaps its NETWORK_EXPORTS.

        Runs alongside the existing 'foursight-smaht' stack: a different STACK_NAME_TOKEN
        gives it a distinct CFN stack name (`c4-foursight-srce-<env>-stack`), and it
        defaults to the parallel foursight configuration secret produced by the appconfig
        stack so its identity does not collide with the portal's GAC.
    """
    STACK_NAME_TOKEN = "foursight-srce"
    STACK_TITLE_TOKEN = "FoursightSRCE"
    SHARING = 'env'

    NETWORK_EXPORTS = C4SRCENetworkExports()

    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):
        with ConfigManager.validate_and_source_configuration():
            self.security_ids = C4SRCENetworkExports.get_security_ids()
            self.subnet_ids = C4SRCENetworkExports.get_subnet_ids()
            self.global_env_bucket = C4AppConfigExports.get_env_bucket()
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            self.trial_creds = get_trial_creds(env_name)
        # Skip C4FoursightSMAHTStack.__init__ (which re-runs the regular network lookup);
        # call the grandparent (BaseC4Stack) directly with the values we just resolved.
        BaseC4Stack.__init__(self, description=description, name=name, tags=tags, account=account)

    def package_foursight_stack(self, args):
        if args.foursight_identity:
            identity = args.foursight_identity
            PRINT(f"Using custom IDENTITY (via --foursight-identity) for FoursightSRCE deployment: {identity}")
        else:
            env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
            identity = Names.foursight_application_configuration_secret(env_name)
            PRINT(f"Using default Foursight IDENTITY for FoursightSRCE deployment: {identity}")
        self.PackageDeploy.build_config_and_package(
            args,
            identity=identity,
            stack_name=self.name.stack_name,
            merge_template=args.merge_template,
            output_file=args.output_file,
            stage=args.stage,
            trial=args.trial,
            global_env_bucket=self.global_env_bucket,
            security_ids=self.security_ids,
            subnet_ids=self.subnet_ids,
            trial_creds=self.trial_creds
        )

    class PackageDeploy(PackageDeploy_from_core):

        CONFIG_BASE = foursight_config_base('foursight-smaht')

        config_dir = dirname(dirname(__file__))
        PRINT(f"Config dir: {config_dir}")

        #: The provision target whose poetry group this deployment needs. `foursight-srce` packages
        #: the same application library as `foursight-smaht`, so it must export the same group.
        PACKAGE_GROUP_TARGET = 'foursight-smaht'

        @classmethod
        def build_config_and_package(cls, args, **kwargs):
            """ Present a package-group target `foursight_core` recognizes, and nothing else.

                `foursight_core.deploy.Deploy.build_config_and_package()` picks the poetry group --
                and so which application library lands in the chalice package -- by matching
                `args.stack` against a hardcoded list of provision targets that knows only
                'foursight-smaht'. 'foursight-srce' is not in that list, so it fell through to the
                foursight_cgap group and shipped a SMaHT `app.py` (which imports `chalicelib_smaht`)
                on top of foursight-cgap's dependencies; the Lambda then failed at startup with
                `Runtime.ImportModuleError: No module named 'chalicelib_smaht'`.

                Rather than broaden that default group or pin an unreleased foursight-core, hand
                core a copy of the arguments whose `stack` it can classify. The copy is local to
                this call: the caller's `args.stack` -- the real deploy target, used for the
                CloudFormation stack name, the change-set upload and error messages -- stays
                'foursight-srce'.
            """
            package_args = copy.copy(args)
            package_args.stack = cls.PACKAGE_GROUP_TARGET
            # super(), not PackageDeploy_from_core: `cls` must stay bound to this subclass so
            # CONFIG_BASE / get_config_filepath() / build_config() remain the SRCE ones.
            return super().build_config_and_package(package_args, **kwargs)
