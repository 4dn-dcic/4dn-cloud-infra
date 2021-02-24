from troposphere import Ref
from troposphere.ec2 import (
    InternetGateway, LocalGatewayRoute, Route, RouteTable, SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Subnet, SubnetCidrBlock, SubnetRouteTableAssociation, Tag, VPC, VPCGatewayAttachment,
)
from src.exceptions import C4NetworkException
from src.util import C4Util


class C4Network(C4Util):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'make' method in C4Infra """

    STACK_CIDR_BLOCK = '10.2.0.0/16'
    DB_PORT_LOW = 5400
    DB_PORT_HIGH = 5499

    @classmethod
    def internet_gateway(cls):
        """ Define Internet Gateway resource. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-internetgateway.html
        """
        name = cls.cf_id('InternetGateway')
        return InternetGateway(
            name,
            Tags=cls.cost_tag_array(name=name)
        )

    @classmethod
    def virtual_private_cloud(cls):
        """ Define VPC resource with specific CIDR block. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-vpc.html
        """
        name = cls.cf_id('VPC')
        return VPC(
            name,
            CidrBlock=cls.STACK_CIDR_BLOCK,
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def internet_gateway_attachment(cls):
        """ Define attaching the internet gateway to the VPC. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-vpc-gateway-attachment.html
        """
        return VPCGatewayAttachment(
            cls.cf_id('AttachGateway'),
            VpcId=Ref(cls.virtual_private_cloud()),
            InternetGatewayId=Ref(cls.internet_gateway()),
        )

    @classmethod
    def main_route_table(cls):
        """ Define main (default) route table resource Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
            TODO(berg) add local gateway association """
        name = cls.cf_id('MainRouteTable')
        return RouteTable(
            name,
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def route_local_gateway(cls):
        """ Define local gateway route Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-localgatewayroute.html
            TODO -- unneeded? currently commented out of infra
        """
        name = cls.cf_id('LocalGatewayRoute')
        return LocalGatewayRoute(
            name,
            DestinationCidrBlock=cls.STACK_CIDR_BLOCK,
            LocalGatewayRouteTableId=Ref(cls.main_route_table()),
            LocalGatewayVirtualInterfaceGroupId=None,  # TODO
            # TODO(berg) Local Gateway Virtual Interface Group Id not found on new account. Is this config needed?
            # TODO aws cli
            # https://awscli.amazonaws.com/v2/documentation/api/latest/reference/ec2/search-local-gateway-routes.html
        )

    @classmethod
    def private_route_table(cls):
        """ Define route table resource *without* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        name = cls.cf_id('PrivateRouteTable')
        return RouteTable(
            name,
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def public_route_table(cls):
        """ Define route table resource *with* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        name = cls.cf_id('PublicRouteTable')
        return RouteTable(
            name,
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def route_internet_gateway(cls):
        """ Defines Internet Gateway route to Public Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        name = cls.cf_id('InternetGatewayRoute')
        return Route(
            name,
            RouteTableId=Ref(cls.public_route_table()),
            GatewayId=Ref(cls.internet_gateway()),
            DestinationCidrBlock='0.0.0.0/0',
            # DependsOn -- TODO needed? see example in src/application.py
        )

    @classmethod
    def build_subnet(cls, name, cidr_block, vpc, az):
        """ Builds a subnet with given name, cidr_block strings, vpc resource, and availability zone (az). """
        return Subnet(
            cls.cf_id(name),
            CidrBlock=cidr_block,
            VpcId=Ref(vpc),
            AvailabilityZone=az,
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def build_subnet_association(cls, subnet, route_table):
        """ Builds a subnet assoociation between a subnet and a route table. What makes a 'public' subnet 'public'
            and a 'private' subnet 'private'. """
        return SubnetRouteTableAssociation(
            cls.cf_id('{}To{}Association'.format(subnet.title, route_table.title)),
            SubnetId=Ref(subnet),
            RouteTableId=Ref(route_table),
        )

    @classmethod
    def public_subnet_a(cls):
        """ Define public subnet A """
        return cls.build_subnet(
            'PublicSubnetA',
            '10.2.5.0/24',
            cls.virtual_private_cloud(),
            'us-east-1a',
        )

    @classmethod
    def public_subnet_b(cls):
        """ Define public subnet B """
        return cls.build_subnet(
            'PublicSubnetB',
            '10.2.7.0/24',
            cls.virtual_private_cloud(),
            'us-east-1b',
        )

    @classmethod
    def private_subnet_a(cls):
        """ Define private subnet A """
        return cls.build_subnet(
            'PrivateSubnetA',
            '10.2.6.0/24',
            cls.virtual_private_cloud(),
            'us-east-1a',
        )

    @classmethod
    def private_subnet_b(cls):
        """ Define private subnet B """
        return cls.build_subnet(
            'PrivateSubnetB',
            '10.2.8.0/24',
            cls.virtual_private_cloud(),
            'us-east-1b',
        )

    @classmethod
    def subnet_associations(cls):
        """ Define a set of subnet associations, which can be unrolled and added to a template. """
        return (cls.build_subnet_association(cls.public_subnet_a(), cls.public_route_table()),
                cls.build_subnet_association(cls.public_subnet_b(), cls.public_route_table()),
                cls.build_subnet_association(cls.private_subnet_a(), cls.private_route_table()),
                cls.build_subnet_association(cls.private_subnet_b(), cls.private_route_table()),)

    @classmethod
    def db_security_group(cls):
        """ Define the database security group """
        group_id = cls.cf_id('DBSecurityGroup')
        return SecurityGroup(
            group_id,
            GroupName=group_id,
            GroupDescription='allows database access on a port range',
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=group_id),
        )

    @classmethod
    def db_inbound_rule(cls):
        """ Returns inbound rules for database (RDS) security group """
        return SecurityGroupIngress(
            cls.cf_id('DBPortRangeAccess'),
            CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
            Description='allows database access on tcp ports 54xx',
            GroupId=Ref(cls.db_security_group()),
            IpProtocol='tcp',
            FromPort=cls.DB_PORT_LOW,
            ToPort=cls.DB_PORT_HIGH,
        )

    @classmethod
    def db_outbound_rule(cls):
        """ Returns outbound rules for database (RDS) security group """
        return SecurityGroupEgress(
            cls.cf_id('DBOutboundAllAccess'),
            CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
            Description='allows outbound traffic to tcp 54xx',
            GroupId=Ref(cls.db_security_group()),
            IpProtocol='tcp',
            FromPort=cls.DB_PORT_LOW,
            ToPort=cls.DB_PORT_HIGH,
        )

    @classmethod
    def https_security_group(cls):
        """ Define the https-only web security group """
        group_id = cls.cf_id('HTTPSSecurityGroup')
        return SecurityGroup(
            group_id,
            GroupName=group_id,
            GroupDescription='allows https-only web access on port 443',
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=group_id),
        )

    @classmethod
    def https_inbound_rule(cls):
        """ Returns inbound rules for https-only web security group """
        return SecurityGroupIngress(
            cls.cf_id('HTTPSInboundAccess'),
            CidrIp='0.0.0.0/0',
            Description='allows inbound traffic on tcp port 443',
            GroupId=Ref(cls.https_security_group()),
            IpProtocol='tcp',
            FromPort=443,
            ToPort=443,
        )

    @classmethod
    def https_outbound_rule(cls):
        """ Returns outbound rules for https-only web security group """
        return SecurityGroupEgress(
            cls.cf_id('HTTPSOutboundAllAccess'),
            CidrIp='0.0.0.0/0',
            Description='allows outbound traffic on tcp port 443',
            GroupId=Ref(cls.https_security_group()),
            IpProtocol='tcp',
            FromPort=443,
            ToPort=443,
        )

    @classmethod
    def beanstalk_security_group(cls):
        """ Returns beanstalk security group for rules needed by beanstalk to access resources """
        group_id = cls.cf_id('BeanstalkSecurityGroup')
        return SecurityGroup(
            group_id,
            GroupName=group_id,
            GroupDescription='allows access needed by Beanstalk Application',
            VpcId=Ref(cls.virtual_private_cloud()),
            Tags=cls.cost_tag_array(name=group_id),
        )

    @classmethod
    def beanstalk_security_rules(cls):
        """ Returns list of inbound and outbound rules needed by beanstalk to access resources """
        return [
            SecurityGroupIngress(
                cls.cf_id('BeanstalkHTTPSInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                cls.cf_id('BeanstalkHTTPSOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupIngress(
                cls.cf_id('BeanstalkWebInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                cls.cf_id('BeanstalkWebOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupIngress(
                cls.cf_id('BeanstalkNTPInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on udp port 123',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupEgress(
                cls.cf_id('BeanstalkNTPOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on udp port 123',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupIngress(
                cls.cf_id('BeanstalkSSHInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                cls.cf_id('BeanstalkSSHOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 22',
                GroupId=Ref(cls.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
        ]