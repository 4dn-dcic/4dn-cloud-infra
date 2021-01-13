from troposphere import Ref
from troposphere.ec2 import (
    InternetGateway, LocalGatewayRoute, Route, RouteTable, Subnet, SubnetCidrBlock,
    SubnetRouteTableAssociation, Tag, VPC, VPCGatewayAttachment,
)
from src.util import C4Util


class C4NetworkException(Exception):
    """ Custom exception type for C4Network class-specific exceptions """
    pass


class C4Network(C4Util):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'mk' method in C4Infra """

    STACK_CIDR_BLOCK = '10.1.0.0/16'

    @classmethod
    def internet_gateway(cls):
        """ Define Internet Gateway resource. """
        return InternetGateway(
            cls.cf_id('InternetGateway')
        )

    @classmethod
    def virtual_private_cloud(cls):
        """ Define VPC resource with specific CIDR block. """
        return VPC(
            cls.cf_id('VPC'),
            CidrBlock=cls.STACK_CIDR_BLOCK,
            Tags=[Tag(key='Name', value=cls.cf_id('VPC-01'))]
        )

    @classmethod
    def internet_gateway_attachment(cls):
        """ Define attaching the internet gateway to the VPC. """
        return VPCGatewayAttachment(
            cls.cf_id('AttachGateway'),
            VpcId=Ref(cls.virtual_private_cloud()),
            InternetGatewayId=Ref(cls.internet_gateway())
        )

    @classmethod
    def main_route_table(cls):
        """ Define main (default) route table resource
            TODO(berg) add local gateway association """
        return RouteTable(
            cls.cf_id('MainRouteTable'),
            VpcId=Ref(cls.virtual_private_cloud()),
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

    @classmethod
    def private_route_table(cls):
        """ Define route table resource *without* an internet gateway attachment
            TODO(berg) add subnet association """
        return RouteTable(
            cls.cf_id('PrivateRouteTable'),
            VpcId=Ref(cls.virtual_private_cloud()),
        )

    @classmethod
    def public_route_table(cls):
        """ Define route table resource *with* an internet gateway attachment
            TODO(berg) add subnet association """
        return RouteTable(
            cls.cf_id('PublicRouteTable'),
            VpcId=Ref(cls.virtual_private_cloud()),
        )

    """
    route_internet_gateway = template.add_resource(
        Route(
            '{}InternetGatewayRoute'.format(STACK_NAME),
            DependsOn=Ref(internet_gateway_attachment),  # TODO(berg) can 'DependsOn' use Ref?
            GatewayId=Ref(internet_gateway),
            DestinationCidrBlock='0.0.0.0/0',
            RouteTableId=Ref(public_route_table)
        )
    )
    """

    @classmethod
    def build_subnet(cls, name, cidr_block, vpc):
        """ Builds a subnet with given name, cidr_block strings and vpc resource """
        return Subnet(
            cls.cf_id(name),
            CidrBlock=cidr_block,
            VpcId=Ref(vpc)
        )

    @classmethod
    def public_subnet_a(cls):
        """ Define public subnet A """
        return cls.build_subnet(
            'PublicSubnetA',
            '10.1.0.0/20',
            cls.virtual_private_cloud()
        )

    @classmethod
    def public_subnet_b(cls):
        """ Define public subnet B """
        return cls.build_subnet(
            'PublicSubnetB',
            '10.1.32.0/20',
            cls.virtual_private_cloud()
        )

    @classmethod
    def private_subnet_a(cls):
        """ Define private subnet A """
        return cls.build_subnet(
            'PrivateSubnetA',
            '10.1.16.0/20',
            cls.virtual_private_cloud()
        )

    @classmethod
    def private_subnet_b(cls):
        """ Define private subnet B """
        return cls.build_subnet(
            'PrivateSubnetB',
            '10.1.48.0/20',
            cls.virtual_private_cloud()
        )
