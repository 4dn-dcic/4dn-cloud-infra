import logging
import sys
from troposphere import Template
from src.data_store import C4DataStore
from src.exceptions import C4InfraException


class C4Infra(C4DataStore):
    """ Creates and manages a generic AWS Infrastructure environment.
        Inherited by specific environment implementations """

    # These class-level globals should be changed in inherited classes
    STACK_NAME = 'c4-generic-stack'
    ID_PREFIX = 'C4Generic'
    DESC = 'AWS CloudFormation C4 template: Generic template for C4 AWS environment'

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
        self.mk_all()
        current_yaml = self.t.to_yaml()
        if stdout:
            print(current_yaml, file=sys.stdout)
            return self.t
        else:
            outfile = self.version_name(current_yaml)
            self.write_outfile(current_yaml, outfile)
            logging.info('Wrote template to {}'.format(outfile))
            return outfile

    def mk_all(self):
        """ Make the template from the class-method specific resources"""
        self.mk_meta()
        self.mk_network()
        self.mk_data_store()

    def mk_meta(self):
        """ Add metadata to the template self.t """
        self.t.set_version(self.VERSION)
        self.t.set_description(self.DESC)

    def mk_network(self):
        """ Add network resources to template self.t """
        logging.debug('Adding network resources to template')

        # Create Internet Gateway, VPC, and attach Internet Gateway to VPC.
        self.t.add_resource(self.internet_gateway())
        self.t.add_resource(self.virtual_private_cloud())
        self.t.add_resource(self.internet_gateway_attachment())

        # Create route tables: main, public, and private. Attach
        # local gateway to main and internet gateway to public.
        self.t.add_resource(self.main_route_table())
        # self.t.add_resource(self.route_local_gateway())  TODO
        self.t.add_resource(self.private_route_table())
        self.t.add_resource(self.public_route_table())
        # self.t.add_resource(self.route_internet_gateway())  TODO
        self.t.add_resource(self.public_subnet_a())
        self.t.add_resource(self.public_subnet_b())
        self.t.add_resource(self.private_subnet_a())
        self.t.add_resource(self.private_subnet_b())
        [self.t.add_resource(i) for i in self.subnet_associations()]

    def mk_data_store(self):
        """ Add data store resources to template self.t """

        # Adds RDS
        self.t.add_resource((self.rds_secret()))
        self.t.add_resource((self.rds_instance()))
        self.t.add_resource((self.rds_secret_attachment()))

        # Adds Elasticsearch
        pass

        # Adds SQS
        pass


class C4InfraTrial(C4Infra):
    """ Creates and manages a CGAP Trial Infrastructure """
    STACK_NAME = 'cgap-trial-stack'
    ID_PREFIX = 'CGAPTrial'
    DESC = 'AWS CloudFormation CGAP template: trial setup for cgap-portal environment'
    ENV = 'dev'
    PROJECT = 'cgap'
    OWNER = 'project'
