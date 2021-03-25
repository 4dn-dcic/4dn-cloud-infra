import logging
import sys
from troposphere import Template
from src.parts.beanstalk import C4Application


class C4Infra(C4Application):
    """ Creates and manages a generic AWS Infrastructure environment.
        Inherited by specific environment implementations """

    # These class-level globals should be changed in inherited classes
    STACK_NAME = 'c4-generic-stack'  #StackName
    ID_PREFIX = 'C4Generic'  # QCName
    DESC = 'AWS CloudFormation C4 template: Generic template for C4 AWS environment'
    RESOURCE_GROUPS = []  # Class methods that add resources to this stack's template when run

    # Version string identifies template capabilities
    # https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/format-version-structure.html
    VERSION = '2010-09-09'

    def __init__(self):
        """ Initialize template self.t, used in mk functions to construct the infrastructure representation. """
        self.t = Template()

    def generate_template(self, stdout=False, remake=True):
        """ Generates a template. If stdout, print to STDOUT and return the Template object. Otherwise, write to
            a file, and return the name of the file. """
        if remake:
            self.t = Template()
        self.add_resource_groups_to_template()
        try:
            current_yaml = self.t.to_yaml()
        except TypeError as e:
            print('TypeError when generating template..did you pass an uninstantiated class method as a Ref?')
            raise e
        if stdout:
            print(current_yaml, file=sys.stdout)
            return self.t
        else:
            outfile = self.version_name(current_yaml)
            self.write_outfile(current_yaml, outfile)
            logging.info('Wrote template to {}'.format(outfile))
            return outfile

    def add_resource_groups_to_template(self, adds_metadata=True):
        """ Reads from self.RESOURCE_GROUPS and executes each class method listed therein. Assumes that a resource group
            adds resources to the template self.t. Always adds metadata_group to the template if adds_metadata is True
            (the default)."""
        if adds_metadata:
            self.metadata_group()
        for group in self.RESOURCE_GROUPS:
            group()  # executes each group in this template, adding these resources to the template

    def metadata_group(self):
        """ Add metadata to the template self.t """
        self.t.set_version(self.VERSION)
        self.t.set_description(self.DESC)

    def network_group(self):
        pass

    def make_data_store(self):
        """ Add data store resources to template self.t """
        pass

    def make_application(self):
        pass


class C4InfraTrialECS(C4Infra):
    """ Creates and manages a CGAP Trial Infrastructure using ECS instead of EB """
    STACK_NAME = 'cgap-ecs-trial-stack'
    ID_PREFIX = 'CGAPTrialECS'
    DESC = 'AWS CloudFormation CGAP template: trial setup for cgap-portal environment'
    ENV = 'dev'
    PROJECT = 'cgap'
    OWNER = 'project'


class C4InfraTrialNetwork(C4Infra):
    """ Creates and manages a CGAP Trial Infrastructure using ECS instead of EB """
    STACK_NAME = 'cgap-trial-network-stack'
    ID_PREFIX = 'CGAPTrialNetwork'
    DESC = 'AWS CloudFormation CGAP template: trial network setup for cgap-portal environment'
    ENV = 'dev'
    PROJECT = 'cgap'
    OWNER = 'project'

    RESOURCE_GROUPS = [self.network_group]
