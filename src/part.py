import logging
import os

from dcicutils.cloudformation_utils import camelize
from dcicutils.exceptions import InvalidParameterError
from dcicutils.misc_utils import remove_prefix
from troposphere import Tag, Tags, Template
from .base import ENV_NAME, ECOSYSTEM
from .c4name import C4Name
from .mixins import StackNameMixin
from .names import Names


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


# dmichaels/2022-06-06: Factored out C4Name class into c4name.py.
# dmichaels/2022-07-08: Factored out StackNameMixin class into mixins.py.


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
