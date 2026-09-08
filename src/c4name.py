# dmichaels/2022-06-06: Factored out from part.py; and commented out print in logical_id().

import hashlib
import re

from datetime import datetime
from dcicutils.cloudformation_utils import camelize
from dcicutils.misc_utils import remove_prefix


class C4Name:
    """ Helper class for working with stack names and resource name construction """
    def __init__(self, name, raw_name=None, title_token=None, string_to_trim=None):
        self.name = name
        self.raw_name = raw_name
        self.stack_name = f'{name}-stack'  # was '{}-stack'.format(name)
        self.logical_id_prefix = title_token or camelize(name)
        self.string_to_trim = string_to_trim or self.logical_id_prefix

    def __str__(self):
        return self.name

    def instance_name(self, suffix):
        """ Build an instance name for an EC2 instance, given a suffix """
        return f'{self.name}-{suffix}'  # was '{0}-{1}'.format(self.name, suffix)

    def logical_id(self, resource, context=""):
        """ Build the Cloud Formation 'Logical Id' for a resource.
            Takes string s and returns s with uniform resource prefix added.
            Can also be used to construct Name tags for resources. """
        # Don't add the prefix redundantly.
        resource_name = str(resource)
        if resource_name.startswith(self.string_to_trim):
            if context:
                context = f"In {context}: "
            else:
                context = ""
            maybe_resource_name = remove_prefix(self.string_to_trim, resource_name, required=False)
            if maybe_resource_name:  # make sure we didn't remove the whole string
                resource_name = maybe_resource_name
        res = self.logical_id_prefix + resource_name
        # print(f"{context}{self}.logical_id({resource!r}) => {res}")
        return res

    @staticmethod
    def bucket_name_from_logical_id(logical_id):
        """ Builds bucket name from a given logical id """
        return '-'.join([a.lower() for a in re.split(r'([A-Z][a-z]*\d*)', logical_id) if a])

    @staticmethod
    def domain_name(name):
        """ Takes in a name string and returns a valid domain name for elasticsearch, which must conform to the domain
            naming convention. """
        return name.lower()  # correct?

    def version_name(self, template_text, file_type='yml') -> str:
        """ Helper method for creating a file name for a specific template version, based on the stack name,
            current date, and the template text's md5sum. Defaults to a yml file type.
            Returns a tuple of (path, version name). """
        stack_name = self.stack_name
        today = str(datetime.now().date()) + datetime.now().strftime('%H:%M:%S')
        md5sum = hashlib.new('md5', bytes(template_text, 'utf-8')).hexdigest()
        # path = 'out/templates/'
        filename = f'{stack_name}-{today}-{md5sum}.{file_type}'
        return filename  # was path, filename
