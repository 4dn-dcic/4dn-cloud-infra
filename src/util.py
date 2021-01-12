import logging
import sys


class C4Util:
    """ Utility methods inherited by troposphere resource building classes: e.g. C4Network"""
    ID_PREFIX = 'C4Util'
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    logging.debug('Loading C4Util')

    @classmethod
    def cf_id(cls, s):
        """ Build the Cloud Formation 'Logical Id' for a resource.
            Takes string s and returns s with uniform resource prefix added.
            Can also be used to construct Name tags for resources. """
        return '{0}{1}'.format(cls.ID_PREFIX, s)

    @staticmethod
    def write_outfile(text, outfile):
        """ Write text to the file `outfile` """
        with open(outfile, 'w', newline='') as file:
            file.write(text)
