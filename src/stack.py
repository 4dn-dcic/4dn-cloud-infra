from src.part import C4Name, C4Tags, C4Account, C4Part
from troposphere import Template
import os
import sys
import logging

# Version string identifies template capabilities. Ref:
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/format-version-structure.html
CLOUD_FORMATION_VERSION = '2010-09-09'


def build_template_from_parts(parts: [C4Part], description) -> Template:
    """ Helper function for building a template from scratch using a list of parts and a description. """
    template = Template()
    template.set_version(CLOUD_FORMATION_VERSION)
    template.set_description(description)
    for p in parts:
        template = p.build_template(template)
    return template


class C4Stack:
    def __init__(self, description, name: C4Name, tags: C4Tags, account: C4Account, parts: [C4Part]):
        self.name = name
        self.tags = tags
        self.account = account
        self.parts = [Part(name=name, tags=tags, account=account) for Part in parts]
        self.description = description
        self.template = build_template_from_parts(self.parts, description)

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

    def print_template(self, stdout=False, remake=True):
        """ Helper method for generating and printing a YAML template.
            If remake is set to true, rebuilds the template. If stdout is set to true, prints to stdout.
            :return (template object, file path, file name)
        """
        if remake:
            self.template = build_template_from_parts(self.parts, self.description)
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
