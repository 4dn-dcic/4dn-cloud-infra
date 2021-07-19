import os
import logging
import re
import sys

from chalicelib.package import PackageDeploy as PackageDeploy_from_cgap
from os.path import dirname
from troposphere import Template, Ref
from .base import COMMON_STACK_PREFIX, ConfigManager
from .constants import CHECK_RUNNER, FOURSIGHT_SECURITY_IDS, FOURSIGHT_SUBNET_IDS, ENV_NAME
from .part import C4Name, C4Tags, C4Account, C4Part
from .parts.datastore import C4Datastore
from .parts.network import C4NetworkExports


# Attempt secret import - if file is not present, will default required values
# into dummy values - intended for use with build - Will 5/27/21
try:
    from src.secrets import S3_ENCRYPT_KEY, Auth0Secret, Auth0Client, ENCODED_ES_SERVER, ENCODED_SECRET
except ImportError:
    S3_ENCRYPT_KEY = 'dummy'
    Auth0Secret = 'dummy'
    Auth0Client = 'dummy'
    ENCODED_ES_SERVER = 'dummy'
    ENCODED_SECRET = 'dummy'


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
        return '<Stack {}>'.format(self.name)

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
            print('TypeError when generating template..did you pass an uninstantiated class method as a Ref?')
            raise e
        path, template_file = self.name.version_name(template_text=current_yaml)
        if stdout:
            print(current_yaml, file=sys.stdout)
        else:
            self.write_template_file(current_yaml, ''.join([path, template_file]))
            logging.info('Wrote template to {}'.format(template_file))
        return self.template, path, template_file


class C4FoursightCGAPStack(BaseC4Stack):

    NETWORK_EXPORTS = C4NetworkExports()

    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):
        with ConfigManager.validate_and_source_configuration():
            self.security_ids = self._get_security_group_ids()
            self.subnet_ids = self._get_subnet_ids()
            self.trial_creds = {
                'S3_ENCRYPT_KEY': S3_ENCRYPT_KEY,
                'CLIENT_ID': Auth0Client,
                'CLIENT_SECRET': Auth0Secret,
                'DEV_SECRET': ENCODED_SECRET,
                'ES_HOST': ENCODED_ES_SERVER,
                'ENV_NAME': os.environ.get(ENV_NAME)  # "cgap-mastertest-kmp"
            }
        # print(f"self.trial_creds['ENV_NAME'] = {self.trial_creds['ENV_NAME']}")
        super().__init__(description, name, tags, account)

    SECURITY_GROUP_EXPORT_PATTERN = re.compile('.*Network.*ExportApplicationSecurityGroup.*')

    @classmethod
    def _get_security_group_ids(cls):
        # TODO: A lot of this can be simplified once it's shown to be working. -kmp 19-Jul-2021
        # TODO: Fetch these dynamically. For the Alpha environment, the orginal value was hardwired as:
        #       ['sg-03f5fdd36be96bbf4'].
        #       Feels like [self.NETWORK_EXPORTS.import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP)]
        #       should do it, but I must be missing something. Trouble is that .import_value returns an import
        #       object, not a string, and it's not json-serializable. -kmp 16-Jul-2021
        try:
            # e.g., name will be 'C4NetworkTrialAlphaExportApplicationSecurityGroup'
            #       or might not contain '...Alpha...'
            # Typically there will be only one output, but we allow several, so the result is returned as a list.
            return ConfigManager.find_stack_outputs(cls.SECURITY_GROUP_EXPORT_PATTERN.match, value_only=True)
            # cloudformation = boto3.resource('cloudformation')
            # # There's probably a constant name to use instead
            # network_stack = cloudformation.Stack('c4-network-trial-alpha-stack')
            # entry = find_association(network_stack.outputs,
            #                          OutputKey='C4NetworkTrialAlphaExportApplicationSecurityGroup')
            # result = entry['OutputValue']
            # print("Discovered security ID from network:", result)
            # return result
        except Exception:
            pass
        security_ids_spec = os.environ.get(FOURSIGHT_SECURITY_IDS)
        if not security_ids_spec:
            raise RuntimeError(f"Environment variable {security_ids_spec} is not set.")
        result = [spec.strip() for spec in security_ids_spec.split(",")]
        return result

    SUBNET_EXPORT_PATTERN = re.compile('.*Network.*ExportPrivateSubnet.*')

    @classmethod
    def _get_subnet_ids(cls):
        # TODO: A lot of this can be simplified once it's shown to be working. -kmp 19-Jul-2021
        # TODO: Fetch these dynamically. For the ALPHA environment, the original value was hardwired as:
        #       ['subnet-09ed0bb672993c7ac', 'subnet-00778b903b357d331']
        #       Feels like [
        #           self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
        #           self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B),
        #       ] should work, but as with _get_subnet_ids above, using an import object here doesn't help.
        #       -kmp 16-Jul-2021
        try:
            # e.g., name will be 'C4NetworkTrialAlphaExportPrivateSubnetA' (or '...B')
            #       or might not contain '...Alpha...'
            # There will be several outputs (currently 2, but maybe more in the future), returned as a list.
            return ConfigManager.find_stack_outputs(cls.SUBNET_EXPORT_PATTERN.match, value_only=True)
        except Exception:
            pass

        subnet_ids_spec = os.environ.get(FOURSIGHT_SUBNET_IDS)
        if not subnet_ids_spec:
            raise RuntimeError(f"Environment variable {subnet_ids_spec} is not set.")
        result = [spec.strip() for spec in subnet_ids_spec.split(",")]
        return result

    def package(self, args):
        self.PackageDeploy.build_config_and_package(
            args,
            security_ids=self.security_ids,
            subnet_ids=self.subnet_ids,
            trial_creds=self.trial_creds,
            check_runner=os.environ.get(CHECK_RUNNER))

    class PackageDeploy(PackageDeploy_from_cgap):

        CONFIG_BASE = PackageDeploy_from_cgap.CONFIG_BASE
        CONFIG_BASE['app_name'] = 'foursight-trial'

        config_dir = dirname(dirname(__file__))
        print(config_dir)
