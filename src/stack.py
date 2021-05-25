from src.part import C4Name, C4Tags, C4Account, C4Part
from chalicelib.package import PackageDeploy as PackageDeploy_from_cgap
from troposphere import Template
from os.path import dirname
import os
import sys
import logging

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
    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account):
        self.hardcoded_security_ids = ['sg-03f5fdd36be96bbf4']  # TODO fetch these dynamically
        self.hardcoded_subnet_ids = ['subnet-09ed0bb672993c7ac', 'subnet-00778b903b357d331']
        super().__init__(description, name, tags, account)

    def package(self, args):
        self.PackageDeploy.build_config_and_package(
            args, security_ids=self.hardcoded_security_ids, subnet_ids=self.hardcoded_subnet_ids)

    class PackageDeploy(PackageDeploy_from_cgap):

        CONFIG_BASE = PackageDeploy_from_cgap.CONFIG_BASE
        CONFIG_BASE['app_name'] = 'foursight-trial'

        config_dir = dirname(dirname(__file__))
        print(config_dir)
