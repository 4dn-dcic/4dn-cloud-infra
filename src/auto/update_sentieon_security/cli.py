# Script for 4dn-cloud-infra to update the application security group for Sentieon.

import argparse
from typing import Optional
from dcicutils.command_utils import yes_or_no
from dcicutils.misc_utils import PRINT
from ...names import Names
from ..utils.aws import Aws
from ..utils.args_utils import add_aws_credentials_args
from ..utils.paths import InfraDirectories
from ..utils.misc_utils import (get_json_config_file_value,
                                exit_with_no_action)
from ..utils.validate_utils import (validate_aws_credentials,
                                    validate_aws_credentials_dir,
                                    validate_aws_credentials_name,
                                    validate_custom_dir,
                                    validate_s3_encrypt_key_id)


def get_application_security_group_name() -> str:
    return Names.application_security_group_name()


def validate_security_group_name(security_group_name: str) -> str:
    if not security_group_name:
        security_group_name = get_application_security_group_name()
        if not security_group_name:
            exit_with_no_action("Unable to determine default application security group name.")
    return security_group_name


def get_sentieon_server_ip(aws_credentials_name: str) -> str:
    sentieon_server_ip_output_key_name = Names.sentieon_output_server_ip_key(aws_credentials_name)
    # TODO: Read the value of the output key name. 
    sentieon_server_ip = "10.0.68.248"
    return sentieon_server_ip


def update_outbound_security_group_rules(aws: Aws, aws_credentials_name: str, security_group_id: str) -> None:
    """
    Adds these outbound security group rules to the given/names security group:

     - Type: Custom TCP
       Protocol: TCP
       Port range: 8990
       Destination: Custom | 10.0.68.248/32 # read from aws outputs
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

     - Type: Custom TCP
       Protocol: TCP
       Port range: 8990
       Destination: Custom <IP-address-of-Senteion-EC2-instance-from-stack-output>/32
       Description: allows communication with sentieon server

    :param aws: Aws object.
    :param aws_credentials_name: AWS credentials name (e.g. cgap-supertest).
    :param security_group_id: Target AWS security group ID.
    """

    # N.B. Had trouble finding values for these protocols (e.g. Source Quench, et cetera).
    # In fact only found a clue at this link:
    # https://github.com/VoyagerInnovations/secgroup_approval/blob/master/revertSecurityGroup.py
    # Where we gleaned the following strategy for setting these which seem to work:
    #
    # Protocol: Destination Unreachable
    #      Use: FromPort = 3 and ToPort = -1
    # Protocol: Echo Request
    #      Use: FromPort = 8 and ToPort = -1
    # Protocol: Source Quench
    #      Use: FromPort = 4 and ToPort = -1
    # Protocol: Time Exceeded
    #      Use: FromPort = 11 and ToPort = -1

    def create_outbound_icmp_security_group_rule(aws: Aws, security_group_id: str, from_port: int) -> None:
        outbound_icmp_security_group_rule = [{
            "IpProtocol": "icmp",
            "FromPort": from_port,
            "ToPort": -1,
            "IpRanges": [{"CidrIp": "0.0.0.0/0", "Description": "ICMP for sentieon server"}],
        }]
        try:
            aws.create_outbound_security_group_rule(security_group_id, outbound_icmp_security_group_rule)
        except Exception as e:
            # TODO
            print("EXCEPTION!!!")
            print(e)

    # Create the outbound ICMP security group rules.
    icmp_port_destination_unreachable = 3
    icmp_port_echo_request = 8
    icmp_port_source_quench = 4
    icmp_port_time_exceeded = 11
    create_outbound_icmp_security_group_rule(aws, security_group_id, icmp_port_destination_unreachable)
    create_outbound_icmp_security_group_rule(aws, security_group_id, icmp_port_echo_request)
    create_outbound_icmp_security_group_rule(aws, security_group_id, icmp_port_source_quench)
    create_outbound_icmp_security_group_rule(aws, security_group_id, icmp_port_time_exceeded)

    # Create the outbound port 8990 security group rules.
    print('xyzzy-1')
    sentieon_server_ip = get_sentieon_server_ip(aws_credentials_name)
    sentieon_server_cidr_ip = sentieon_server_ip + "/32"
    outbound_security_group_rule = [{
        "IpProtocol": "tcp",
        "FromPort": 8990,
        "ToPort": 8990,
        "IpRanges": [{"CidrIp": sentieon_server_cidr_ip,
                      "Description": "allows communication with sentieon server"}],
    }]
    try:
        print('xyzzy-2')
        aws.create_outbound_security_group_rule(security_group_id, outbound_security_group_rule)
        print('xyzzy-3')
    except Exception as e:
        # TODO
        print('xyzzy-4')
        print("EXCEPTION!!!")
        print(e)


def update_inbound_security_group_rules(aws: Aws, security_group_id: str) -> None:
    """
    Adds these inbound security group rules to the given/names security group:

    - Type: All ICMP - IPv4
      Protocol: ICMP
      Port range: All
      Destination: Custom 0.0.0.0/0
      Description: ICMP for sentieon server

    :param aws: Aws object.
    :param security_group_id: Target AWS security group ID.
    """
    pass


def update_sentieon_security(args) -> None:
    """
    Main logical entry point for this script.
    Gathers, prints, confirms, and updates the application security group for Sentieon.

    :param args: Command-line arguments values.
    """

    # Gather the basic info.
    custom_dir, config_file = validate_custom_dir(args.custom_dir)
    aws_credentials_name = validate_aws_credentials_name(args.aws_credentials_name, config_file)
    aws_credentials_dir = validate_aws_credentials_dir(args.aws_credentials_dir, custom_dir)

    # Print header and basic info.
    PRINT(f"Updating 4dn-cloud-infra application security group Sentieon.")
    PRINT(f"Your custom directory: {custom_dir}")
    PRINT(f"Your custom config file: {config_file}")
    PRINT(f"Your AWS credentials name: {aws_credentials_name}")

    # Validate and print basic AWS credentials info.
    aws, aws_credentials = validate_aws_credentials(aws_credentials_dir,
                                                    args.aws_access_key_id,
                                                    args.aws_secret_access_key,
                                                    args.aws_region,
                                                    args.aws_session_token)
    # TODO

    security_group_name = validate_security_group_name(args.security_group_name)
    print(f"Target security group name: {security_group_name}")

    security_group_id = aws.find_security_group_id(security_group_name)
    if not security_group_id:
        exit_with_no_action(f"Unable to determine security group ID from name: {security_group_name}")
    print(f"Target security group ID: {security_group_id}")

    yes = yes_or_no(f"Update this security group ({security_group_id}) with outbound rules Sentieon?")
    if not yes:
        exit_with_no_action()

    # Update the outbound security group rules.
    update_outbound_security_group_rules(aws, aws_credentials_name, security_group_id)



def main(override_argv: Optional[list] = None) -> None:
    """
    Main entry point for this script. Parses command-line arguments and calls the main logical entry point.

    :param override_argv: Raw command-line arguments for this invocation.
    """
    argp = argparse.ArgumentParser()
    add_aws_credentials_args(argp)
    argp.add_argument("--custom-dir", required=False, default=InfraDirectories.CUSTOM_DIR,
                      help=f"Alternate custom config directory to default: {InfraDirectories.CUSTOM_DIR}.")
    argp.add_argument("--security-group-name", required=False,
                      help=f"Security group name to updaate. Default is C4NetworkMainApplicationSecurityGroup.")
    argp.add_argument("--no-confirm", required=False,
                      dest="confirm", action="store_false",
                      help="Behave as if all confirmation questions were answered yes.")
    args = argp.parse_args(override_argv)

    if (args.aws_access_key_id or args.aws_secret_access_key) and \
       not (args.aws_access_key_id and args.aws_secret_access_key):
        exit_with_no_action("Either none or both --aws-access-key-id and --aws-secret-access-key must be specified.")

    update_sentieon_security(args)


if __name__ == "__main__":
    main()
