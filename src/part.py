import hashlib
import logging
import os
import sys
from datetime import datetime
from troposphere import Tag, Template, ImportValue, Sub
from src.exceptions import C4InfraException


class QCTags:
    def __init__(self, env='test', project='test', owner='test'):
        self.env = env
        self.project = project
        self.owner = owner

    def cost_tag_array(self, name=None):
        """ Build a Tag array given the three cost allocation tags: env, project, and owner. This can be appended
            to a Tag array with additional info (such as the Name tag)"""
        cost_tags = [Tag(k='env', v=self.env), Tag(k='project', v=self.project), Tag(k='owner', v=self.owner)]
        if name:
            return [Tag(k='Name', v=name)] + cost_tags
        else:
            return cost_tags


class QCAccount:
    def __init__(self, account_number):
        self.account_number = str(account_number)


class QCName:
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


class QCPart:
    """ Utility methods inherited by troposphere resource building classes: e.g. C4Network"""
    # Ref: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/pseudo-parameter-reference.html

    def __init__(self, name: QCName, tags: QCTags, account: QCAccount, **kwargs):
        self.name = name
        self.tags = tags
        self.account = account
        super().__init__(**kwargs)

    def __str__(self):
        return str(self.name)

    def build_template(self, template: Template) -> Template:
        return template
