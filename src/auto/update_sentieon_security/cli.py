# Script for 4dn-cloud-infra to update the application security group for Sentieon.

import argparse
from botocore.exceptions import ClientError as Boto3ClientException
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ...names import Names
from ..utils.aws import Aws
from ..utils.args_utils import (
    add_aws_credentials_args,
    validate_aws_credentials_args,
)
from ..utils.paths import InfraDirectories
from ..utils.misc_utils import (
    exit_with_no_action,
    print_exception,
    setup_and_action,
)
from ..utils.validate_utils import (
    validate_and_get_aws_credentials,
)


def get_sentieon_compute_node_inbound_security_group_rules() -> list:
    """
    Returns these inbound security group rules which should be defined for the AWS target security group:

    - Type: All ICMP - IPv4
      Protocol: ICMP
      Port range: All
      Destination: Custom 0.0.0.0/0
      Description: ICMP for sentieon server

    :return: Outbound security group rules to define.
    """
    return [{
        "IpProtocol": "icmp",
        "FromPort": -1,
        "ToPort": -1,
        "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "ICMP for sentieon server"}],
    }]


def get_sentieon_compute_node_outbound_security_group_rules(sentieon_ip_address: str) -> list:
    """
    Returns these outbound security group rules which should be defined for the AWS target security group:

    - Type: Custom TCP
      Protocol: TCP
      Port range: 8990
      Destination: Custom <ip-address-of-sentieon-ec2-instance-from-stack-output>/32
      Description: allows communication with sentieon server

    - Type: Custom ICMP - IPv4
      Protocol: Destination Unreachable
      Port range: All
      Destination: Custom | 0.0.0.0/0
      Description: ICMP for sentieon server

    - Type: Custom ICMP - IPv4
      Protocol: Echo Request
      Port range: N/A
      Destination: Custom | 0.0.0.0/0
      Description: ICMP for sentieon server

    - Type: Custom ICMP - IPv4
      Protocol: Source Quench
      Port range: N/A
      Destination: Custom | 0.0.0.0/0
      Description: ICMP for sentieon server

    - Type: Custom ICMP - IPv4
      Protocol: Time Exceeded
      Port range: All
      Destination: Custom | 0.0.0.0/0
      Description: ICMP for sentieon server

    :param sentieon_ip_address: Sentieon server IP address.
    :return: Outbound security group rules to define.
    """
    def outbound_tcp_security_group_rule(ip_address: str) -> dict:
        return {
            "IpProtocol": "tcp",
            "FromPort": 8990,
            "ToPort": 8990,
            "IpRanges": [{"CidrIp": ip_address + "/32",
                          "Description": "allows communication with sentieon server"}],
        }

    def outbound_icmp_security_group_rule(from_port: int) -> dict:
        return {
            "IpProtocol": "icmp",
            "FromPort": from_port,
            "ToPort": -1,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "ICMP for sentieon server"}],
        }

    # N.B. Had trouble finding values for the ICMP protocols (e.g. Source Quench, et cetera).
    # In fact only found a clue at this link:
    # Ref: https://github.com/VoyagerInnovations/secgroup_approval/blob/master/revertSecurityGroup.py
    # Where we gleaned the following strategy for setting these, which does seem to work:
    # FYI note this link says: ICMP has no concept of ports, as TCP/UDP do, but instead uses types/codes.
    # Ref: https://www.sciencedirect.com/topics/computer-science/internet-control-message-protocol
    #
    # Protocol: Destination Unreachable
    #      Use: FromPort = 3 and ToPort = -1
    # Protocol: Echo Request
    #      Use: FromPort = 8 and ToPort = -1
    # Protocol: Source Quench
    #      Use: FromPort = 4 and ToPort = -1
    # Protocol: Time Exceeded
    #      Use: FromPort = 11 and ToPort = -1

    return [
        outbound_tcp_security_group_rule(sentieon_ip_address),
        outbound_icmp_security_group_rule(3),  # Destination unreachable
        outbound_icmp_security_group_rule(8),  # Echo request
        outbound_icmp_security_group_rule(4),  # Source quench
        outbound_icmp_security_group_rule(11)  # Time exceeded
    ]


def validate_and_get_sentieon_server_ip_address(aws: Aws,
                                                aws_credentials_name: str,
                                                sentieon_ip_address: str,
                                                sentieon_stack_name: str,
                                                sentieon_stack_output_ip_address_key_name: str) -> str:
    """
    Validates, prints, and returns the Sentieon server IP address based on the given Sentieon IP
    address (if specified), AWS credentials name, Sentieon AWS stack name (if specified),
    and Sentieon AWS stack output IP address key name (if specified); exit on error (if not set).

    :param aws: Aws object.
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :param sentieon_ip_address: Sention server IP address.
    :param sentieon_stack_name: AWS stack name for Sentieon server.
    :param sentieon_stack_output_ip_address_key_name: AWS stack output key name for Sentieon server IP address.
    :return: Sentieon server IP address.
    """

    if not sentieon_ip_address:

        # Get the Sentieon AWS stack name.
        if not sentieon_stack_name:
            sentieon_stack_name = Names.sentieon_stack_name(aws_credentials_name)
            if not sentieon_stack_name:
                exit_with_no_action("Unable to determine Sentieon stack name.")
        print(f"Sentieon stack name: {sentieon_stack_name}")

        # Get the Sentieon AWS stack output IP address key name.
        if not sentieon_stack_output_ip_address_key_name:
            sentieon_stack_output_ip_address_key_name = Names.sentieon_output_server_ip_key(aws_credentials_name)
            if not sentieon_stack_output_ip_address_key_name:
                exit_with_no_action("Unable to determine Sentieon stack output IP address key name.")
        print(f"Sentieon stack output IP address key name: {sentieon_stack_output_ip_address_key_name}")

        # Get the Sentieon server IP address (from the Outputs of the Sentieon AWS stack).
        sentieon_ip_address = aws.get_stack_output_value(sentieon_stack_name,
                                                         sentieon_stack_output_ip_address_key_name)
        if not sentieon_ip_address:
            exit_with_no_action("Unable to determine Sentieon server IP address.")

    print(f"Sentieon server IP address: {sentieon_ip_address}")
    return sentieon_ip_address


def validate_and_get_target_security_group_name(aws: Aws, security_group_name: str) -> (str, str):
    """
    Validates the given target security group name and returns its value; defaults to a value
    returned by 4d-cloud-infra code if not given. And also returns the security group ID
    associated with this security group name; exit on error (if not set).

    :param aws: Aws object.
    :param security_group_name: Target AWS security group name.
    :return: Tuple containing AWS security group name and associated security group ID.
    """
    if not security_group_name:
        security_group_name = Names.application_security_group_name()
        if not security_group_name:
            exit_with_no_action("Unable to determine default application security group name.")
    security_group_id = aws.find_security_group_id(security_group_name)
    if not security_group_id:
        exit_with_no_action(f"Unable to determine security group ID from name: {security_group_name}")
    print(f"Target security group name: {security_group_name}")
    print(f"Target security group ID: {security_group_id}")
    return security_group_name, security_group_id


def summarize_security_group_rules_to_define(security_group_id: str, sentieon_ip_address: str) -> None:
    """
    Print a summary of the inbound/outbound rules to be defined.

    :param security_group_id: Security group ID.
    :param sentieon_ip_address: IP address of the Sentieon server.
    """
    inbound_security_group_rules_to_define = get_sentieon_compute_node_inbound_security_group_rules()
    for rule in inbound_security_group_rules_to_define:
        print(f"Inbound security group ({security_group_id}) rule to define:"
              f" {Aws.get_security_group_rule_display_value(rule)}")
    outbound_security_group_rules_to_define = \
        get_sentieon_compute_node_outbound_security_group_rules(sentieon_ip_address)
    for rule in outbound_security_group_rules_to_define:
        print(f"Outbound security group ({security_group_id}) rule to define:"
              f" {Aws.get_security_group_rule_display_value(rule)}")


def print_duplicate_security_group_message(exception: Exception,
                                           security_group_id: str,
                                           security_group_rule: dict,
                                           outbound: bool) -> bool:
    """
    If the given exception is for a boto3 duplicate security group rule creation, then
    prints an error for this, with info about the given security group ID, security group
    type (inbound or outbound), and security group rule, and returns True; otherwise returns False.

    :param exception: Exception to examine for boto3 duplicate security group rule creation.
    :param security_group_id: AWS security group ID.
    :param security_group_rule: AWS security group rule.
    :param outbound: True if related to outbound (egress) rule, otherwise inbound (ingress).
    :return: True if the given exception is for a boto3 duplicate security rule creation, otherwise False.
    """
    if isinstance(exception, Boto3ClientException):
        if exception.response:
            error = exception.response.get("Error")
            if error:
                error_code = error.get("Code")
                if error_code == "InvalidPermission.Duplicate":
                    print(f"{'Outbound' if outbound else 'Inbound'} security group ({security_group_id}) rule"
                          f" already exists: {Aws.get_security_group_rule_display_value(security_group_rule)}")
                    return True
    return False


def update_inbound_security_group_rules(
        aws: Aws,
        security_group_id: str,
        force: bool = False
) -> None:
    """
    Adds the inbound security group rules to the given/named AWS target security group:

    :param aws: Aws object.
    :param security_group_id: Target AWS security group ID.
    :param force: True to replace any existing security group rule before creation.
    """

    # Get the inbound security group rules to define.
    rules = get_sentieon_compute_node_inbound_security_group_rules()

    # Get a list of inbound security group rules for the given security group ID.
    existing_rules = aws.get_inbound_security_group_rules(security_group_id)

    for rule in rules:
        existing_rule = aws.find_inbound_security_group_rule(existing_rules, rule)
        if existing_rule:
            existing_rule_id = existing_rule.get("SecurityGroupRuleId")
            if force:
                print(f"Removing existing inbound security group rule ({existing_rule_id}):"
                      f" {Aws.get_security_group_rule_display_value(rule)}")
                aws.delete_inbound_security_group_rule(security_group_id, existing_rule_id)
            else:
                print(f"Inbound security group rule ({existing_rule_id})"
                      f" already exists: {Aws.get_security_group_rule_display_value(rule)} -> No action")
                continue
        try:
            print(f"Creating inbound security"
                  f" group ({security_group_id}) rule: {Aws.get_security_group_rule_display_value(rule)}", end="")
            created_rule_id = aws.create_inbound_security_group_rule(security_group_id, rule)
            print(f" -> {created_rule_id}")
        except Exception as e:
            if not print_duplicate_security_group_message(e, security_group_id, rule, outbound=False):
                print_exception(e)


def update_outbound_security_group_rules(
        aws: Aws,
        security_group_id: str,
        sentieon_ip_address: str,
        force: bool = False
) -> None:
    """
    Adds the outbound security group rules to the given/named AWS target security group:

    :param aws: Aws object.
    :param security_group_id: Target AWS security group ID.
    :param sentieon_ip_address: Sentieon server IP address.
    :param force: True to replace any existing security group rule before creation.
    """

    # Get the outbound security group rules to define.
    rules = get_sentieon_compute_node_outbound_security_group_rules(sentieon_ip_address)

    # Get a list of outbound security group rules for the given security group ID.
    existing_rules = aws.get_outbound_security_group_rules(security_group_id)

    # See if any rules already exist for the rules to define.
    for rule in rules:
        existing_rule = aws.find_outbound_security_group_rule(existing_rules, rule)
        if existing_rule:
            existing_rule_id = existing_rule.get("SecurityGroupRuleId")
            if force:
                print(f"Removing existing outbound security group rule ({existing_rule_id}):"
                      f" {Aws.get_security_group_rule_display_value(rule)}")
                aws.delete_outbound_security_group_rule(security_group_id, existing_rule_id)
            else:
                print(f"Outbound security group rule ({existing_rule_id})"
                      f" already exists: {Aws.get_security_group_rule_display_value(rule)} -> No action")
                continue
        try:
            print(f"Creating outbound security"
                  f" group ({security_group_id}) rule: {Aws.get_security_group_rule_display_value(rule)}", end="")
            created_rule_id = aws.create_outbound_security_group_rule(security_group_id, rule)
            print(f" -> {created_rule_id}")
        except Exception as e:
            if not print_duplicate_security_group_message(e, security_group_id, rule, outbound=False):
                print_exception(e)


def update_sentieon_security(
        aws_access_key_id: str,
        aws_credentials_dir: str,
        aws_credentials_name: str,
        aws_region: str,
        aws_secret_access_key: str,
        aws_session_token: str,
        custom_dir: str,
        force: bool,
        security_group_name: str,
        sentieon_ip_address: str,
        sentieon_stack_name: str,
        sentieon_stack_output_ip_address_key_name: str,
        show: bool
) -> None:
    """
    Main logical entry point for this script.
    Gathers, prints, confirms, and updates the application security group for Sentieon.
    """
    PRINT(f"Updating 4dn-cloud-infra application security group for use as Sentieon compute node.")

    with setup_and_action() as setup_and_action_state:

        # Validate/get and print basic AWS credentials info.
        aws = validate_and_get_aws_credentials(aws_credentials_name,
                                               aws_credentials_dir,
                                               custom_dir,
                                               aws_access_key_id,
                                               aws_secret_access_key,
                                               aws_region,
                                               aws_session_token,
                                               show)

        # Validate/get and print the Sentieon server IP address.
        sentieon_ip_address = validate_and_get_sentieon_server_ip_address(aws,
                                                                          aws.credentials_name,
                                                                          sentieon_ip_address,
                                                                          sentieon_stack_name,
                                                                          sentieon_stack_output_ip_address_key_name)

        # Validate/get and print the target security group name, and get associated security group ID.
        security_group_name, security_group_id = validate_and_get_target_security_group_name(aws, security_group_name)

        # Print summary of security group rules to define.
        summarize_security_group_rules_to_define(security_group_id, sentieon_ip_address)

        # Confirm with user before taking action.
        yes = yes_or_no(f"Define these security group rules for security group ({security_group_id})?")
        if not yes:
            exit_with_no_action()

        # Start creating the inbound/outbound security group rules.
        setup_and_action_state.note_action_start()

        # Update the inbound security group rules.
        update_inbound_security_group_rules(aws, security_group_id, force)

        # Update the outbound security group rules.
        update_outbound_security_group_rules(aws, security_group_id, sentieon_ip_address, force)


def main(override_argv: Optional[list] = None) -> None:
    """
    Main entry point for this script. Parses command-line arguments and calls the main logical entry point.

    :param override_argv: Raw command-line arguments for this invocation.
    """
    argp = argparse.ArgumentParser()
    add_aws_credentials_args(argp)
    argp.add_argument("--custom-dir", required=False, default=InfraDirectories.CUSTOM_DIR,
                      help=f"Alternate custom config directory to default: {InfraDirectories.CUSTOM_DIR}.")
    argp.add_argument("--force", action="store_true", required=False,
                      help="Force replace any existing security group rule.")
    argp.add_argument("--no-confirm", required=False,
                      dest="confirm", action="store_false",
                      help="Behave as if all confirmation questions were answered yes.")
    argp.add_argument("--security-group-name", required=False,
                      help=f"Security group name to updaate. Default is C4NetworkMainApplicationSecurityGroup.")
    argp.add_argument("--sentieon-ip-address", required=False,
                      help=f"Sentieon IP address.")
    argp.add_argument("--sentieon-stack-name", required=False,
                      help=f"Sentieon AWS stack name to get IP address from.")
    argp.add_argument("--sentieon-stack-output-ip-address-key-name", required=False,
                      help=f"Sentieon AWS stack output IP address key name to get IP address from.")
    argp.add_argument("--show", action="store_true", required=False,
                      help="Show any senstive info in plaintext.")
    args = argp.parse_args(override_argv)
    validate_aws_credentials_args(args)

    update_sentieon_security(
        args.aws_access_key_id,
        args.aws_credentials_dir,
        args.aws_credentials_name,
        args.aws_region,
        args.aws_secret_access_key,
        args.aws_session_token,
        args.custom_dir,
        args.force,
        args.security_group_name,
        args.sentieon_ip_address,
        args.sentieon_stack_name,
        args.sentieon_stack_output_ip_address_key_name,
        args.show
    )


if __name__ == "__main__":
    main()
