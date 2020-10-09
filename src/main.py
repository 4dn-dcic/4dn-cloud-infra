import argparse

from troposphere import Ref, Template
from troposphere.ec2 import InternetGateway, LocalGatewayRoute, Route, RouteTable, Subnet, SubnetCidrBlock, \
    SubnetRouteTableAssociation, VPC, VPCGatewayAttachment

# Version string identifies template capabilities
# https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/format-version-structure.html
VERSION = '2010-09-09'
STACK_NAME = 'CGAPTrial'
STACK_CIDR_BLOCK = '10.1.0.0/16'


def configure_network_layout(template):

    # Create Internet Gateway, VPC, and attach Internet Gateway to VPC.

    internet_gateway = template.add_resource(
        InternetGateway(
            '{}InternetGateway'.format(STACK_NAME)
        )
    )

    virtual_private_cloud = template.add_resource(
        VPC(
            '{}VPC'.format(STACK_NAME),
            CidrBlock=STACK_CIDR_BLOCK
        )
    )

    internet_gateway_attachment = template.add_resource(
        VPCGatewayAttachment(
            '{}AttachGateway'.format(STACK_NAME),
            VpcId=Ref(virtual_private_cloud),
            InternetGatewayId=Ref(internet_gateway)
        )
    )

    # Create route tables: main, public, and private.
    # Attach local gateway to main and internet gateway to public.

    # TODO(berg) add local gateway association
    main_route_table = template.add_resource(
        RouteTable(
            '{}MainRouteTable'.format(STACK_NAME),
            VpcId=Ref(virtual_private_cloud),
        )
    )

    # TODO(berg) Local Gateway Virtual Interface Group Id not found on new account. Is this config needed?
    """
    # TODO(berg) add local gateway association to vpc
    route_local_gateway = template.add_resource(
        LocalGatewayRoute(
            "{}LocalGatewayRoute".format(STACK_NAME),
            DestinationCidrBlock=STACK_CIDR_BLOCK,
            LocalGatewayRouteTableId=Ref(main_route_table),
            LocalGatewayVirtualInterfaceGroupId=None

        )
    )
    """

    # TODO(berg) add subnet association
    private_route_table = template.add_resource(
        RouteTable(
            '{}PrivateRouteTable'.format(STACK_NAME),
            VpcId=Ref(virtual_private_cloud),
        )
    )

    # TODO(berg) add subnet association
    public_route_table = template.add_resource(
        RouteTable(
            '{}PublicRouteTable'.format(STACK_NAME),
            VpcId=Ref(virtual_private_cloud),
        )
    )

    route_internet_gateway = template.add_resource(
        Route(
            '{}InternetGatewayRoute'.format(STACK_NAME),
            DependsOn=Ref(internet_gateway_attachment),  # TODO(berg) can 'DependsOn' use Ref?
            GatewayId=Ref(internet_gateway),
            DestinationCidrBlock='0.0.0.0/0',
            RouteTableId=Ref(public_route_table)
        )
    )

    # TODO(berg) build_subnet('letter', public=true)
    public_subnet_a = template.add_resource(
        Subnet(
            '{}PublicSubnetA'.format(STACK_NAME),
            CidrBlock='10.1.0.0/20',
            VpcId=Ref(virtual_private_cloud)
        )
    )

    private_subnet_a = template.add_resource(
        Subnet(
            '{}PrivateSubnetA'.format(STACK_NAME),
            CidrBlock='10.1.16.0/20',
            VpcId=Ref(virtual_private_cloud)
        )
    )

    public_subnet_b = template.add_resource(
        Subnet(
            '{}PublicSubnetB'.format(STACK_NAME),
            CidrBlock='10.1.32.0/20',
            VpcId=Ref(virtual_private_cloud)
        )
    )

    private_subnet_b = template.add_resource(
        Subnet(
            '{}PrivateSubnetB'.format(STACK_NAME),
            CidrBlock='10.1.48.0/20',
            VpcId=Ref(virtual_private_cloud)
        )
    )

    return template


def create_new_account_template():
    template = Template()
    template.set_version(VERSION)

    template.set_description(
        "AWS CloudFormation CGAP template: trial setup for cgap-portal environment"
    )

    template = configure_network_layout(template)

    return template


def generate_template(args):
    # TODO(berg): as account migration proceeds, rename from create_new -> create_$actualname
    template = create_new_account_template()
    print(template.to_json())


def main():
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    subparsers = parser.add_subparsers(help='Commands')

    parser_generate = subparsers.add_parser('generate', help='Generate Cloud Formation template as json')
    parser_generate.set_defaults(func=generate_template)

    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
