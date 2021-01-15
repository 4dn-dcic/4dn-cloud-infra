import hashlib
import logging
import sys
from datetime import datetime
from troposphere import Tag


class C4Util:
    """ Utility methods inherited by troposphere resource building classes: e.g. C4Network"""
    ID_PREFIX = 'C4Util'
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logging.debug('Loading C4Util')

    ENV = 'test'
    PROJECT = 'test'
    OWNER = 'test'

    @classmethod
    def version_name(cls, yaml_template):
        """ Returns a version file name, based on the current date and the contents of the yaml """
        d = str(datetime.now().date())
        h = hashlib.new('md5', bytes(yaml_template, 'utf-8')).hexdigest()
        return '{date}-cf-template-{hash}.yml'.format(date=d, hash=h)

    @classmethod
    def cf_id(cls, s):
        """ Build the Cloud Formation 'Logical Id' for a resource.
            Takes string s and returns s with uniform resource prefix added.
            Can also be used to construct Name tags for resources. """
        return '{0}{1}'.format(cls.ID_PREFIX, s)

    @classmethod
    def cost_tag_array(cls):
        """ Build a Tag array given the three cost allocation tags: env, project, and owner. This can be appended
            to a Tag array with additional info (such as the Name tag)"""
        return [Tag(k='env', v=cls.ENV), Tag(k='project', v=cls.PROJECT), Tag(k='owner', v=cls.OWNER)]

    @staticmethod
    def write_outfile(text, outfile):
        """ Write text to the file `outfile` """
        with open(outfile, 'w', newline='') as file:
            file.write(text)
