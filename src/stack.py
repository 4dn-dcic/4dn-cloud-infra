from src.part import QCName, QCTags, QCAccount, QCPart
from troposphere import Template
import os
import sys
import logging
from datetime import datetime
import hashlib


def build_template_from_parts(parts: [QCPart]) -> Template:
    template = Template()
    for p in parts:
        template = p.build_template(template)
    return template


class QCStack:
    def __init__(self, name: QCName, tags: QCTags, account: QCAccount, parts: [QCPart], **kwargs):
        self.name = name
        self.tags = tags
        self.account = account
        self.parts = [Part(name=name, tags=tags, account=account) for Part in parts]
        self.template = build_template_from_parts(self.parts)
        super().__init__()  # **kwargs throws an error

    def __str__(self):
        return '<Stack {}>'.format(self.name)


    @staticmethod
    def write_outfile(text, outfile):
        """ Write text to the file `outfile` """

        # Verify the outfile path exists, and create if it doesn't
        path, filename = os.path.split(outfile)
        if os.path.exists(path) is False:
            os.makedirs(path)

        with open(outfile, 'w', newline='') as file:
            file.write(text)

    @classmethod
    def version_name(cls, yaml_template):
        """ Returns a version file name, based on the current date and the contents of the yaml """
        d = str(datetime.now().date())
        h = hashlib.new('md5', bytes(yaml_template, 'utf-8')).hexdigest()
        return 'out/cf-yml/{date}-cf-template-{hash}.yml'.format(date=d, hash=h)

    def print_template(self, stdout=False, remake=True):
        """ Generates a template. If stdout, print to STDOUT and return the Template object. Otherwise, write to
            a file, and return the name of the file. """
        if remake:
            self.template = build_template_from_parts(self.parts)
        try:
            current_yaml = self.template.to_yaml()
        except TypeError as e:
            print('TypeError when generating template..did you pass an uninstantiated class method as a Ref?')
            raise e
        if stdout:
            print(current_yaml, file=sys.stdout)
            return self.template
        else:
            outfile = self.version_name(current_yaml)
            self.write_outfile(current_yaml, outfile)
            logging.info('Wrote template to {}'.format(outfile))
            return outfile
