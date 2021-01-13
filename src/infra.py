import logging
import sys
from troposphere import Template
from src.network import C4Network
from src.db import C4DB


class C4InfraException(Exception):
    """ Custom exception type for C4Infra class-specific exceptions """
    pass


class C4Infra(C4Network, C4DB):
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

    def generate_template(self, outfile=None, remake=True):
        """ Generates a template """
        if remake:
            self.t = Template()
        try:
            self.mk_all()
        except Exception as e:
            # ... TODO
            raise e
        try:
            current_yaml = self.t.to_yaml()
        except Exception as e:
            # ... TODO
            raise e
        if not outfile:
            print(self.t.to_yaml(), file=sys.stdout)
        else:
            current_yaml = self.t.to_yaml()
            self.write_outfile(current_yaml, outfile)
            logging.info('Wrote template to {}'.format(outfile))
        return self.t

    def mk_all(self):
        """ Make the template from the class-method specific resources"""
        self.mk_meta()
        self.mk_network()
        self.mk_db()

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

    def mk_db(self):
        """ Add database resources to template self.t """
        pass


class C4InfraTrial(C4Infra):
    """ Creates and manages a CGAP Trial Infrastructure """
    STACK_NAME = 'cgap-trial'
    ID_PREFIX = 'CGAPTrial'
    DESC = 'AWS CloudFormation CGAP template: trial setup for cgap-portal environment'
