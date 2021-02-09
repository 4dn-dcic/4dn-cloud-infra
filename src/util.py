import hashlib
import logging
import sys
from datetime import datetime
from troposphere import Tag
from src.exceptions import C4InfraException


class C4Util:
    """ Utility methods inherited by troposphere resource building classes: e.g. C4Network"""
    ID_PREFIX = 'C4Util'
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logging.debug('Loading C4Util')

    ENV = 'test'
    PROJECT = 'test'
    OWNER = 'test'
    ACCOUNT_NUMBER = '645819926742'  # 'trial' account number; overridden for other accounts TODO more generic?

    @classmethod
    def domain_name(cls, name):
        """ Takes in a name string and returns a valid domain name for elasticsearch, which must conform to the domain
            naming convention. """
        return name.lower()

    @classmethod
    def version_name(cls, yaml_template):
        """ Returns a version file name, based on the current date and the contents of the yaml """
        d = str(datetime.now().date())
        h = hashlib.new('md5', bytes(yaml_template, 'utf-8')).hexdigest()
        return 'out/cf-yml/{date}-cf-template-{hash}.yml'.format(date=d, hash=h)

    @classmethod
    def cf_id(cls, s):
        """ Build the Cloud Formation 'Logical Id' for a resource.
            Takes string s and returns s with uniform resource prefix added.
            Can also be used to construct Name tags for resources. """
        return '{0}{1}'.format(cls.ID_PREFIX, s)

    @classmethod
    def cost_tag_array(cls, name=None):
        """ Build a Tag array given the three cost allocation tags: env, project, and owner. This can be appended
            to a Tag array with additional info (such as the Name tag)"""
        cost_tags = [Tag(k='env', v=cls.ENV), Tag(k='project', v=cls.PROJECT), Tag(k='owner', v=cls.OWNER)]
        if name:
            return [Tag(k='Name', v=name)] + cost_tags
        else:
            return cost_tags

    @staticmethod
    def write_outfile(text, outfile):
        """ Write text to the file `outfile` """
        with open(outfile, 'w', newline='') as file:
            file.write(text)
