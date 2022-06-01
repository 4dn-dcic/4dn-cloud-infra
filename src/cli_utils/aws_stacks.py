# --------------------------------------------------------------------------------------------------
# Simple script to view AWS stacks and related info.
# By default prints all stacks, and optionally all associated Outputs key/values.
# TODO: Use regex for pattern rather than just simple contains.
# TODO: Move the args stuff inside the if __main__.
#
# usage: aws-stacks [--name stack-name-pattern]
#                   {
#                   | [ --outputs | --output output-key-pattern]
#                   | [ --resources | --resource resource-name-pattern ]
#                   | [ --parameters | -parameter  parameter-name-pattern ]
#                   }
#                   [--verbose]
#
# If --name with a simple pattern is given then limit stacks to those
# whose stack names contains the specified simple pattern (case-insensitive).
#
# If --outputs is given then prints all outputs key/values for each stack.
#
# If --output with a simple pattern is given then limit outputs key/values
# to those whose keys contains the specified simple pattern (case-insensitive).
#
# If --resource with a simple pattern is given then limit resources names/types
# to those whose names contains the specified simple pattern (case-insensitive).
#
# If --resources is given then prints all resources names/types for each stack.
#
# If --parameters is given then prints all parameters key/values for each stack.
#
# If --parameter with a simple pattern is given then limit parameters key/values
# to those whose keys contains the specified simple pattern (case-insensitive).
#
# Only one of --output(s) or --resource(s) or --parameter(s) may be specified.
#
# If --verbose is given then include export name with the outputs keys/values.
# --------------------------------------------------------------------------------------------------

import argparse
import boto3
import json

args_parser = argparse.ArgumentParser()
args_parser.add_argument("--name", type=str, required=False)
args_parser.add_argument("--outputs", action="store_true", required=False)
args_parser.add_argument("--output", type=str, required=False)
args_parser.add_argument("--verbose", action="store_true", required=False)
args_parser.add_argument("--resources", action="store_true", required=False)
args_parser.add_argument("--resource", type=str, required=False)
args_parser.add_argument("--parameters", action="store_true", required=False)
args_parser.add_argument("--parameter", type=str, required=False)
args = args_parser.parse_args()

description = ""
mutually_exclusive_options_count = 0
if args.outputs or args.output:
    description = " with Outputs"
    mutually_exclusive_options_count += 1
if args.resources or args.resource:
    description = " with Resources"
    mutually_exclusive_options_count += 1
if args.parameters or args.parameter:
    description = " with Parameters"
    mutually_exclusive_options_count += 1

if mutually_exclusive_options_count > 1:
    print("Must specify only one of: --output(s) --resource(s) --parameter(s)")
    exit(1)

def print_aws_stacks():

    print(f"AWS Stacks{description}", end = "")
    if args.name:
        print(" / name containing: " + args.name, end = "")
    if args.output:
        print(" / output keys containing: " + args.output, end = "")
    if args.resource:
        print(" / resource name containing: " + args.resource, end = "")
    if args.parameter:
        print(" / parameter name containing: " + args.parameter, end = "")
    print()

    c4 = boto3.client('cloudformation')
    for stack in c4.describe_stacks()["Stacks"]:
        stack_name = stack["StackName"]
        if args.name and not args.name.lower() in stack_name.lower():
            continue
        stack_updated = stack["LastUpdatedTime"]
        print("%-15s (updated: %s)" % (stack_name, stack_updated.astimezone().strftime("%Y:%m:%d %H:%M:%S")))
        if args.outputs or args.output:
            for stack_output in sorted(stack["Outputs"], key=lambda key: key["OutputKey"]):
                stack_output_key = stack_output["OutputKey"]
                if args.output and not args.output.lower() in stack_output_key.lower():
                    continue
                stack_output_value = stack_output["OutputValue"]
                stack_output_export_name = stack_output.get("ExportName")
                print(" - %s: %s" % (stack_output_key, stack_output_value))
                # print(" - %s:" % (stack_output_key))
                # print("   %s" % (stack_output_value))
                if args.verbose and stack_output_export_name:
                    print("   %s (export name)" % (stack_output_export_name))
        elif args.resources or args.resource:
            for stack_resource in sorted(c4.describe_stack_resources(StackName=stack_name)["StackResources"], key=lambda key: key["LogicalResourceId"].lower()):
                stack_resource_name = stack_resource["LogicalResourceId"]
                stack_resource_type = stack_resource["ResourceType"]
                if args.resource and not args.resource.lower() in stack_resource_name.lower():
                    continue
                print("- %s: %s" % (stack_resource_name, stack_resource_type))
        elif args.parameters or args.parameter:
            stack_parameters = stack.get("Parameters")
            if stack_parameters:
                for stack_parameter in sorted(stack_parameters, key=lambda key: key["ParameterKey"]):
                    stack_parameter_key = stack_parameter["ParameterKey"]
                    if args.parameter and not args.parameter.lower() in stack_parameter_key.lower():
                        continue
                    stack_parameter_value = stack_parameter["ParameterValue"]
                    print(" - %s: %s" % (stack_parameter_key, stack_parameter_value))
                    # print(" - %s:" % (stack_parameter_key))
                    # print("   %s" % (stack_parameter_value))

def main():
    print_aws_stacks()

if __name__ == "__main__":
    main()
