import hashlib
from datetime import datetime
from troposphere import Tag, Template


class QCTags:
    """ Helper class for working with cost allocation tags """
    def __init__(self, env='test', project='test', owner='test'):
        self.env = env
        self.project = project
        self.owner = owner

    def cost_tag_array(self, name=None):
        """ Build a Tag array given the three cost allocation tags: env, project, and owner. This can be appended
            to a Tag array with additional info (such as the Name tag) """
        cost_tags = [Tag(k='env', v=self.env), Tag(k='project', v=self.project), Tag(k='owner', v=self.owner)]
        if name:
            return [Tag(k='Name', v=name)] + cost_tags
        else:
            return cost_tags


class QCAccount:
    """ Helper class for working with an AWS account """
    def __init__(self, account_number):
        self.account_number = str(account_number)


class QCName:
    """ Helper class for working with stack names and resource name construction """
    def __init__(self, name):
        self.name = name
        self.stack_name = '{}-stack'.format(name)
        self.logical_id_prefix = ''.join([i.capitalize() for i in name.split('-')])

    def __str__(self):
        return self.name

    def logical_id(self, resource):
        """ Build the Cloud Formation 'Logical Id' for a resource.
            Takes string s and returns s with uniform resource prefix added.
            Can also be used to construct Name tags for resources. """
        return '{0}{1}'.format(self.logical_id_prefix, resource)

    @staticmethod
    def domain_name(name):
        """ Takes in a name string and returns a valid domain name for elasticsearch, which must conform to the domain
            naming convention. """
        return name.lower()  # correct?

    def version_name(self, template_text, file_type='yml'):
        """ Helper method for creating a file name for a specific template version, based on the stack name,
            current date, and the template text's md5sum. Defaults to a yml file type.
            Returns a tuple of (path, version name). """
        stack_name = self.stack_name
        today = str(datetime.now().date())
        md5sum = hashlib.new('md5', bytes(template_text, 'utf-8')).hexdigest()
        path = 'out/templates/'
        filename = '{stack_name}-{today}-{md5sum}.{file_type}'.format(
            stack_name=stack_name, today=today, md5sum=md5sum, file_type=file_type)

        return path, filename


class QCPart:
    """ Inheritable class for building parts of a stack by:
        - adding to a stack's template
        - collecting the helper classes used for the stack
    """
    # Ref: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/pseudo-parameter-reference.html

    def __init__(self, name: QCName, tags: QCTags, account: QCAccount, **kwargs):
        self.name = name
        self.tags = tags
        self.account = account
        super().__init__(**kwargs)

    def __str__(self):
        return str(self.name)

    def build_template(self, template: Template) -> Template:
        """ Overwrite this to construct this part's addition to the template. Add resources to template, and return the
            completed template resource.
            :type template: Template
        """
        return template
