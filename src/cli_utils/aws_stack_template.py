# --------------------------------------------------------------------------------------------------
# Simple script to view AWS stack templates.
#
# usage: aws-stacks-template stack-name
# --------------------------------------------------------------------------------------------------

import argparse
import boto3
import json
import sys
import yaml
from collections import OrderedDict

def print_aws_stack_template(stack_name):

    c4 = boto3.client('cloudformation')
    stack_template = c4.get_template(StackName=stack_name)
    stack_template_body = stack_template["TemplateBody"]
    if isinstance(stack_template_body, OrderedDict):
        #
        # For some reason for our AWS stack c4-foursight-cgap-supertest-stack
        # in particular, we get back an OrderedDict, which we print as JSON;
        # having trouble converting to YAML.
        #
        stack_template_json = json.dumps(stack_template_body, default=str, indent=2)
        print(stack_template_json)
    else:
        #
        # For other AWS stacks like c4-datastore-cgap-supertest-stack,
        # we get a simple string containing the YAML for the template.
        #
        print(stack_template_body)

def main():
    stack_name = sys.argv[1]
    print_aws_stack_template(stack_name)

if __name__ == "__main__":
    main()
