import logging
import sys
from troposphere import Template
from src.application import C4Application
from src.exceptions import C4InfraException


class C4Infra(C4Application):
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
        self.make_all()
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

    def make_all(self):
        """ Make the template from the class-method specific resources"""
        self.make_meta()
        self.make_network()
        self.make_data_store()
        self.make_application()

    def make_meta(self):
        """ Add metadata to the template self.t """
        self.t.set_version(self.VERSION)
        self.t.set_description(self.DESC)

    def make_network(self):
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
        self.t.add_resource(self.db_security_group())
        self.t.add_resource(self.db_outbound_rule())
        self.t.add_resource(self.db_inbound_rule())

    def make_data_store(self):
        """ Add data store resources to template self.t """

        # Adds RDS
        self.t.add_resource(self.rds_secret())
        self.t.add_resource(self.rds_parameter_group())
        self.t.add_resource(self.rds_instance())
        self.t.add_resource(self.rds_subnet_group())
        self.t.add_resource(self.rds_secret_attachment())

        # Adds Elasticsearch
        self.t.add_resource(self.elasticsearch_instance())

        # Adds SQS
        self.t.add_resource(self.sqs_instance())

    def make_application(self):
        """ Add Beanstalk application to template self.t """

        # Adds application
        self.t.add_resource(self.beanstalk_application())


class C4InfraTrial(C4Infra):
    """ Creates and manages a CGAP Trial Infrastructure """
    STACK_NAME = 'cgap-trial-stack'
    ID_PREFIX = 'CGAPTrial'
    DESC = 'AWS CloudFormation CGAP template: trial setup for cgap-portal environment'
    ENV = 'dev'
    PROJECT = 'cgap'
    OWNER = 'project'
