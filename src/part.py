import hashlib
import logging
import os
import re

from datetime import datetime
from dcicutils.cloudformation_utils import camelize
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import remove_prefix
from troposphere import Tag, Tags, Template
from .base import ENV_NAME, ECOSYSTEM, COMMON_STACK_PREFIX, COMMON_STACK_PREFIX_CAMEL_CASE


logger = logging.getLogger(__name__)


class C4Tags:
    """ Helper class for working with cost allocation tags """
    def __init__(self, env='test', project='test', owner='test'):
        self.env = env
        self.project = project
        self.owner = owner

    def cost_tag_obj(self, name=None):
        """ Build a Tags object given the three cost allocation tags: env, project, and owner, along with the optional
            Name tag, if name is provided. This is used by some, but not all, troposphere classes. """
        if name:
            return Tags(env=self.env, project=self.project, owner=self.owner, Name=name)
        else:
            return Tags(env=self.env, project=self.project, owner=self.owner)

    def cost_tag_array(self, name=None):
        """ Build a Tag array given the three cost allocation tags: env, project, and owner. This can be appended
            to a Tag array with additional info (such as the Name tag) """
        cost_tags = [Tag(k='env', v=self.env), Tag(k='project', v=self.project), Tag(k='owner', v=self.owner)]
        if name:
            return [Tag(k='Name', v=name)] + cost_tags
        else:
            return cost_tags


class C4Account:
    """ Helper class for working with an AWS account """
    def __init__(self, account_number, creds_file):  # previous default '~/.aws_test/test_creds.sh'
        self.account_number = str(account_number)
        self.creds_file = creds_file

    def command_with_creds(self, cmd):
        """ Builds a command that begins with sourcing the correct creds """
        return 'source {creds_file} && {cmd}'.format(creds_file=self.creds_file, cmd=cmd)

    def run_command(self, cmd):
        """ Runs cmd, properly sourcing this account's creds beforehand """
        command_with_creds = self.command_with_creds(cmd)
        os.system(command_with_creds)


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
        print(f"{context}{self}.logical_id({resource!r}) => {res}")
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


class StackNameMixin:

    STACK_NAME_TOKEN = None
    STACK_TITLE_TOKEN = None
    STACK_TAGS = None
    SHARING = 'env'

    _SHARING_QUALIFIERS = {
        'env': f"{ENV_NAME}",
        'ecosystem': f"{ECOSYSTEM}",
        'account': "",
    }

    @classmethod
    def stack_title_token(cls):
        return cls.STACK_TITLE_TOKEN or camelize(cls.STACK_NAME_TOKEN)

    @classmethod
    def suggest_sharing_qualifier(cls):
        sharing = cls.SHARING
        if sharing not in cls._SHARING_QUALIFIERS:
            raise InvalidParameterError(parameter=f'{cls}.SHARING', value=sharing,
                                        options=list(cls._SHARING_QUALIFIERS.keys()))
        return cls._SHARING_QUALIFIERS[sharing]

    @classmethod
    def suggest_stack_name(cls, name=None):
        title_token = cls.stack_title_token()
        if name:  # for stack names, defer to the name of that stack as declared in alpha_stacks.py
            name_camel = camelize(name)
            return C4Name(name=f'{COMMON_STACK_PREFIX}{name}',
                          raw_name=name,
                          title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{title_token}{name_camel}'
                                       if title_token else None),
                          string_to_trim=name_camel)
        import pdb; pdb.set_trace()
        qualifier = cls.suggest_sharing_qualifier()
        qualifier_suffix = f"-{qualifier}"
        qualifier_camel = camelize(qualifier)
        name_token = cls.STACK_NAME_TOKEN

        return C4Name(name=f'{COMMON_STACK_PREFIX}{name_token}{qualifier_suffix}',
                      title_token=(f'{COMMON_STACK_PREFIX_CAMEL_CASE}{title_token}{qualifier_camel}'
                                   if title_token else None),
                      string_to_trim=qualifier_camel)



class C4Part(StackNameMixin):
    """ Inheritable class for building parts of a stack by:
        - adding to a stack's template
        - collecting the helper classes used for the stack
    """
    # Ref: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/pseudo-parameter-reference.html

    def __init__(self, name: C4Name, tags: C4Tags, account: C4Account):
        self.name = name
        self.tags = tags
        self.account = account

    def __str__(self):
        return str(self.name)

    def build_template(self, template: Template) -> Template:
        """ Overwrite this to construct this part's addition to the template. Add resources to template, and return the
            completed template resource.
            :type template: Template
        """
        return template

    def trim_name(self, item):
        item_string = str(item)
        res = remove_prefix(self.name.string_to_trim, item_string, required=False)
        if res != item_string:
            print(f"Reducing {item_string!r} to {res!r}.")
        else:
            print(f"Not reducing {item_string!r} because {self.name.string_to_trim} wasn't there.")
        return res

    def trim_names(self, items):
        return [self.trim_name(item) for item in items]
