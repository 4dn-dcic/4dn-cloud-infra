import logging
import re

from troposphere import Ref, GetAtt, Output, Template
from troposphere.ec2 import (
    InternetGateway, Route, RouteTable, SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Subnet, SubnetRouteTableAssociation, VPC, VPCGatewayAttachment, NatGateway, EIP, Instance, NetworkInterfaceProperty,
    VPCEndpoint,
)
from ..base import ConfigManager, exportify
from typing import List
# from ..constants import FOURSIGHT_SUBNET_IDS, FOURSIGHT_SECURITY_IDS
from ..exports import C4Exports
from ..part import C4Part


class C4NetworkExports(C4Exports):
    """ Helper class for working with network exported resources and their input values """
    VPC = 'VPC'  # 'ExportVPC'

    _SUBNETS = {
        'PrivateSubnetA': {'name': 'PrivateSubnetA', 'cidr_block': '10.0.0.0/18', 'az': 'us-east-1a', 'kind': 'private'},
        'PublicSubnetA': {'name': 'PublicSubnetA', 'cidr_block': '10.0.64.0/18', 'az': 'us-east-1a', 'kind': 'public'},
        'PrivateSubnetB': {'name': 'PrivateSubnetB', 'cidr_block': '10.0.128.0/18', 'az': 'us-east-1b', 'kind': 'private'},
        'PublicSubnetB': {'name': 'PublicSubnetB', 'cidr_block': '10.0.192.0/18', 'az': 'us-east-1b', 'kind': 'public'},
    }

    PRIVATE_SUBNETS = [exportify(name) for name, entry in _SUBNETS.items() if entry['kind'] == 'private']

    # PRIVATE_SUBNET_A = exportify(PRIVATE_SUBNETS[0])  # deprecated
    # PRIVATE_SUBNET_B = exportify(PRIVATE_SUBNETS[1])  # deprecated

    PUBLIC_SUBNETS = [exportify(name) for name, entry in _SUBNETS.items() if entry['kind'] == 'public']

    # PUBLIC_SUBNET_A = exportify(PUBLIC_SUBNETS[0])  # deprecated
    # PUBLIC_SUBNET_B = exportify(PUBLIC_SUBNETS[1])  # deprecated

    # XXX: Can we name this something more generic? -Will
    # I got rid of the word "Export". Is that enough? -kmp 14-Aug-2021
    APPLICATION_SECURITY_GROUP =  exportify('ApplicationSecurityGroup')
    DB_SECURITY_GROUP = exportify('DBSecurityGroup')
    HTTPS_SECURITY_GROUP = exportify('HTTPSSecurityGroup')

    # e.g., name will be 'C4NetworkTrialAlphaExportApplicationSecurityGroup'
    #       or might not contain '...Alpha...'
    _APPLICATION_SECURITY_GROUP_EXPORT_PATTERN = re.compile('.*Network.*ApplicationSecurityGroup.*')

    @classmethod
    def get_security_ids(cls):
        # Typically there will be only one output, but we allow several, so the result is returned as a list.
        # e.g., for the Alpha environment, the orginal value was hardwired as: ['sg-03f5fdd36be96bbf4']
        computed_result = ConfigManager.find_stack_outputs(cls._APPLICATION_SECURITY_GROUP_EXPORT_PATTERN.match,
                                                           value_only=True)
        return computed_result

    # e.g., name will be 'C4NetworkTrialAlphaExportPrivateSubnetA' (or '...B')
    #       or might not contain '...Alpha...'
    _PRIVATE_SUBNET_EXPORT_PATTERN = re.compile('.*Network.*PrivateSubnet.*')

    @classmethod
    def get_subnet_ids(cls):
        # TODO: This could perhaps be better computed from cls._SUBNETS -kmp 14-Aug-2021
        # There will be several outputs (currently 2, but maybe more in the future), returned as a list.
        # e.g., for the Alpha environment, the original value was hand-coded as:
        #       ['subnet-09ed0bb672993c7ac', 'subnet-00778b903b357d331']
        computed_result = ConfigManager.find_stack_outputs(cls._PRIVATE_SUBNET_EXPORT_PATTERN.match, value_only=True)
        return computed_result

    def __init__(self):
        parameter = 'NetworkStackNameParameter'
        # could perhaps reference C4NetworkPart.name.stack_name
        super().__init__(parameter)


class C4Network(C4Part):
    """ Note: when reading this code 'application' roughly refers to the AWS service running
        the CGAP Portal, whether it be Elastic Beanstalk or ECS.
    """

    # "The allowed block size is between a /16 netmask (65,536 IP addresses) and /28 netmask (16 IP addresses).
    #  After you've created your VPC, you can associate secondary CIDR blocks with the VPC.)"
    # Source: https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Subnets.html
    # The public/private subnets will need to be allocated from within this space.
    CIDR_BLOCK = '10.0.0.0/16'  # Allocate maximum allowed range of IP addresses (10.0.0.0 to 10.0.255.255)

    DB_PORT_LOW = 5400
    DB_PORT_HIGH = 5499
    EXPORTS = C4NetworkExports()

    def build_template(self, template: Template) -> Template:
        """ Add network resources to template """
        logging.debug('Adding network resources to template')

        # Create Internet Gateway, VPC, and attach Internet Gateway to VPC.
        for i in [self.internet_gateway(), self.virtual_private_cloud(), self.internet_gateway_attachment()]:
            template.add_resource(i)
        # Add VPC output
        template.add_output(self.output_virtual_private_cloud())

        # Add route tables
        for i in [self.main_route_table(), self.private_route_table(), self.public_route_table()]:
            template.add_resource(i)

        # # Add subnets
        # public_subnet_a, public_subnet_b, \
        # private_subnet_a, private_subnet_b = self.public_subnet_a(), self.public_subnet_b(), \
        #                                      self.private_subnet_a(), self.private_subnet_b()
        # template.add_resource(public_subnet_a)
        # template.add_resource(public_subnet_b)
        # template.add_resource(private_subnet_a)
        # template.add_resource(private_subnet_b)

        for subnet in self.private_subnets():
            template.add_resource(subnet)
        for subnet in self.public_subnets():
            template.add_resource(subnet)

        # Add subnet outputs
        for i in self.subnet_outputs():
            template.add_output(i)

        # # Create NAT gateways
        # public_a_nat_eip = self.nat_eip('PublicSubnetA')
        # public_a_nat_gateway = self.nat_gateway(public_a_nat_eip, public_subnet_a)
        # template.add_resource(public_a_nat_eip)
        # template.add_resource(public_a_nat_gateway)
        # public_b_nat_eip = self.nat_eip('PublicSubnetB')
        # public_b_nat_gateway = self.nat_gateway(public_b_nat_eip, public_subnet_b)
        # template.add_resource(public_b_nat_eip)
        # template.add_resource(public_b_nat_gateway)

        first_time = True

        for public_subnet in self.public_subnets():
            # import pdb; pdb.set_trace()
            public_nat_eip = self.nat_eip(public_subnet)
            public_nat_gateway = self.nat_gateway(public_nat_eip, public_subnet)
            template.add_resource(public_nat_eip)
            template.add_resource(public_nat_gateway)
            if first_time:
                template.add_resource(self.route_nat_gateway(public_nat_gateway))  # Why only the Public A gateway??
                first_time = False

        template.add_resource(self.route_internet_gateway())

        # # Add Internet Gateway to public route table, NAT Gateway to private route table
        # # XXX: why is this only possible with public_a_nat_gateway?
        # for i in [self.route_internet_gateway(),
        #           self.route_nat_gateway(public_a_nat_gateway)]:
        #     template.add_resource(i)

        # Add subnet-to-route-table associations
        for i in self.subnet_associations():
            template.add_resource(i)

        # Add security groups
        for i in [self.db_security_group(), self.https_security_group(), self.application_security_group()]:
            template.add_resource(i)
        # Add security group outputs
        for i in [self.db_security_group_output(), self.https_security_group_output(),
                  self.application_security_group_output()]:
            template.add_output(i)

        # Add db inbound and outbound rules
        for i in [self.db_inbound_rule(), self.db_outbound_rule()]:
            template.add_resource(i)

        # Add https inbound and outbound rules
        for i in [self.https_inbound_rule(), self.https_outbound_rule()]:
            template.add_resource(i)

        # Add Application security rules
        for i in self.application_security_rules():
            template.add_resource(i)

        # Add Bastion Host
        # template.add_resource(self.bastion_host())
        # Add VPC Interface Endpoints for AWS Services (to reduce NAT Gateway charges)
        # NOTE: the service names vary by region, so this may need to be configurable
        # See: aws ec2 describe-vpc-endpoint-services
        template.add_resource(self.create_vpc_interface_endpoint('sqs',
                                                                 'com.amazonaws.us-east-1.sqs'))
        template.add_resource(self.create_vpc_interface_endpoint('ecrapi',
                                                                 'com.amazonaws.us-east-1.ecr.api'))
        template.add_resource(self.create_vpc_interface_endpoint('ecrdkr',
                                                                 'com.amazonaws.us-east-1.ecr.dkr'))
        template.add_resource(self.create_vpc_interface_endpoint('secretsmanager',
                                                                 'com.amazonaws.us-east-1.secretsmanager'))
        template.add_resource(self.create_vpc_interface_endpoint('ssm',
                                                                 'com.amazonaws.us-east-1.ssm'))
        template.add_resource(self.create_vpc_interface_endpoint('logs',
                                                                 'com.amazonaws.us-east-1.logs'))
        template.add_resource(self.create_vpc_interface_endpoint('ec2',
                                                                 'com.amazonaws.us-east-1.ec2'))
        template.add_resource(self.create_vpc_interface_endpoint('ebs',
                                                                 'com.amazonaws.us-east-1.ebs'))
        template.add_resource(self.create_vpc_interface_endpoint('lambda',
                                                                 'com.amazonaws.us-east-1.lambda'))
        template.add_resource(self.create_vpc_interface_endpoint('states',
                                                                 'com.amazonaws.us-east-1.states'))
        # Add VPC Gateway endpoints
        template.add_resource(self.create_vpc_gateway_endpoint('dynamodb',
                                                               'com.amazonaws.us-east-1.dynamodb'))
        template.add_resource(self.create_vpc_gateway_endpoint('s3',
                                                               'com.amazonaws.us-east-1.s3'))
        return template

    def internet_gateway(self) -> InternetGateway:
        """ Define Internet Gateway resource. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-internetgateway.html
        """
        logical_id = self.name.logical_id('InternetGateway')
        return InternetGateway(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id)
        )

    def virtual_private_cloud(self) -> VPC:
        """ Define VPC resource with specific CIDR block. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-vpc.html
        """
        logical_id = self.name.logical_id('VPC')
        return VPC(
            logical_id,
            CidrBlock=self.CIDR_BLOCK,
            Tags=self.tags.cost_tag_array(name=logical_id),
            EnableDnsSupport=True,
            EnableDnsHostnames=True
        )

    def output_virtual_private_cloud(self) -> Output:
        """ Define output for VPC resource for cross-stack compatibility. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        export_name = C4NetworkExports.VPC
        logical_id = self.name.logical_id(export_name)
        resource = self.virtual_private_cloud()
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
        return output

    def internet_gateway_attachment(self) -> VPCGatewayAttachment:
        """ Define attaching the internet gateway to the VPC. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-vpc-gateway-attachment.html
        """
        logical_id = self.name.logical_id('AttachGateway')
        return VPCGatewayAttachment(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            InternetGatewayId=Ref(self.internet_gateway()),
        )

    def nat_eip(self, subnet: Subnet) -> EIP:
        """ Define an Elastic IP for a NAT gateway. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-eip.html
        """
        logical_id = self.name.logical_id("EIPfor" + self.trim_name(subnet.title), context='nat_eip')
        return EIP(
            logical_id,
            Domain='vpc',
        )

    def nat_gateway(self, eip: EIP, subnet: Subnet) -> NatGateway:
        """ Define a NAT Gateway. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-natgateway.html
        """
        logical_id = self.name.logical_id("NATGatewayFor" + self.trim_name(subnet.title), context='nat_gateway')
        return NatGateway(
            logical_id,
            DependsOn=eip.title,
            AllocationId=GetAtt(eip, 'AllocationId'),
            SubnetId=Ref(subnet),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def main_route_table(self):
        """ Define main (default) route table resource Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
            TODO(berg) add local gateway association """
        logical_id = self.name.logical_id('MainRouteTable', context='main_route_table')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def private_route_table(self):
        """ Define route table resource *without* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        logical_id = self.name.logical_id('PrivateRouteTable', context='private_route_table')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def public_route_table(self):
        """ Define route table resource *with* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        logical_id = self.name.logical_id('PublicRouteTable', context='public_route_table')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def route_internet_gateway(self):
        """ Defines Internet Gateway route to Public Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        logical_id = self.name.logical_id('InternetGatewayRoute', context='route_internet_gateway')
        return Route(
            logical_id,
            RouteTableId=Ref(self.public_route_table()),
            GatewayId=Ref(self.internet_gateway()),
            DestinationCidrBlock='0.0.0.0/0',
            # DependsOn -- TODO needed? see example in src/beanstalk.py
        )

    def route_nat_gateway(self, public_subnet_nat_gateway: NatGateway):
        """ Defines NAT Gateway route to Private Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        logical_id = self.name.logical_id(public_subnet_nat_gateway.title + "Route", context="route_nat_gateway")
        return Route(
            logical_id,
            RouteTableId=Ref(self.private_route_table()),
            DestinationCidrBlock='0.0.0.0/0',
            NatGatewayId=Ref(public_subnet_nat_gateway)
            # DependsOn -- TODO needed? see example in src/beanstalk.py
        )

    def build_subnet(self, subnet_name, cidr_block, vpc, az) -> Subnet:
        """ Builds a subnet with given name, cidr_block strings, vpc resource, and availability zone (az). """
        logical_id = self.name.logical_id(subnet_name, context='build_subnet')
        return Subnet(
            logical_id,
            CidrBlock=cidr_block,
            VpcId=Ref(vpc),
            AvailabilityZone=az,
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def build_subnet_association(self, subnet, route_table) -> SubnetRouteTableAssociation:
        """ Builds a subnet association between a subnet and a route table. What makes a 'public' subnet 'public'
            and a 'private' subnet 'private'. """
        logical_id = self.name.logical_id('{}To{}Association'.format(self.trim_name(subnet.title),
                                                                     self.trim_name(route_table.title)))
        return SubnetRouteTableAssociation(
            logical_id,
            SubnetId=Ref(subnet),
            RouteTableId=Ref(route_table),
        )

    # NOTE: These CIDR IP ranges need to exist within the space defined by the CIDR_BLOCK class variable.
    #       To compute the implications of that, use a tool like https://cidr.xyz/
    #       * To succeed (avoiding "The maximum number of addresses has been reached.") we had to expand
    #         the default number of EIPs from 5 to a larger number (we used 100).
    #       * This partitions the primary CIDR_BLOCK space into 4 parts of 16,384 addresses each,
    #         leaving no additional room. A secondary block can be added if other subnets are needed.
    #         See: https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Subnets.html#vpc-resize

    PRIVATE_SUBNETS = None
    PUBLIC_SUBNETS = None

    SUBNETS_KEY_MAP = {'private': 'PRIVATE_SUBNETS', 'public': 'PUBLIC_SUBNETS'}

    def public_subnets(self):
        return self._get_subnets('public')

    def private_subnets(self):
        return self._get_subnets('private')

    def _get_subnets(self, kind) -> List[Subnet]:
        subnets_key = self.SUBNETS_KEY_MAP[kind]
        subnets = getattr(self, subnets_key)
        if not subnets:
            subnets = {}
            for name, entry in C4NetworkExports._SUBNETS.items():
                if entry['kind'] == kind:
                    cidr_block = entry['cidr_block']
                    az = entry['az']
                    subnet = self.build_subnet(name, cidr_block, self.virtual_private_cloud(), az)
                    subnets[name] = subnet
            setattr(self, subnets_key, subnets)
        result = list(subnets.values())
        # print(f"_get_subnets({kind}) => {result}")
        return result

    # def private_subnet_a(self) -> Subnet:
    #     """ Define private subnet A """
    #     return self.private_subnets()[0]  # TODO: remove this scaffolding method when debugged
    #     # return self.build_subnet('PrivateSubnetA', '10.0.0.0/18', self.virtual_private_cloud(),
    #     #                          'us-east-1a')
    #
    # def public_subnet_a(self) -> Subnet:
    #     """ Define public subnet A """
    #     return self.public_subnets()[0]  # TODO: remove this scaffolding method when debugged
    #     # return self.build_subnet('PublicSubnetA', '10.0.64.0/18', self.virtual_private_cloud(), 'us-east-1a')
    #
    # def private_subnet_b(self) -> Subnet:
    #     """ Define private subnet B """
    #     return self.private_subnets()[1]  # TODO: remove this scaffolding method when debugged
    #     # return self.build_subnet('PrivateSubnetB', '10.0.128.0/18', self.virtual_private_cloud(),
    #     #                          'us-east-1b')
    #
    # def public_subnet_b(self) -> Subnet:
    #     """ Define public subnet B """
    #     return self.public_subnets()[1]  # TODO: remove this scaffolding method when debugged
    #     # return self.build_subnet('PublicSubnetB', '10.0.192.0/18', self.virtual_private_cloud(), 'us-east-1b')

    def subnet_outputs(self) -> [Output]:
        """ Define outputs for all subnets, for cross-stack compatibility. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        # subnet_exports = [
        #     (self.public_subnet_a(), C4NetworkExports.PUBLIC_SUBNET_A),
        #     (self.public_subnet_b(), C4NetworkExports.PUBLIC_SUBNET_B),
        #     (self.private_subnet_a(), C4NetworkExports.PRIVATE_SUBNET_A),
        #     (self.private_subnet_b(), C4NetworkExports.PRIVATE_SUBNET_B),
        # ]
        # outputs = []
        # for subnet, export_name in subnet_exports:
        #     logical_id = self.name.logical_id(export_name)
        #     output = Output(
        #         logical_id,
        #         Value=Ref(subnet),
        #         Export=self.EXPORTS.export(export_name),
        #     )
        #     outputs.append(output)

        outputs = []
        for subnet_dict in [self.PUBLIC_SUBNETS, self.PRIVATE_SUBNETS]:
            for export_name, subnet in subnet_dict.items():
                logical_id = self.name.logical_id(export_name)
                output = Output(
                    logical_id,
                    Value=Ref(subnet),
                    Export=self.EXPORTS.export(export_name),
                )
                outputs.append(output)

        return outputs

    def subnet_associations(self) -> [SubnetRouteTableAssociation]:
        """ Define a list of subnet associations, which can be unrolled and added to a template. """

        public_route_table = self.public_route_table()
        private_route_table = self.private_route_table()
        return ([self.build_subnet_association(subnet, public_route_table) for subnet in self.public_subnets()] +
                [self.build_subnet_association(subnet, private_route_table) for subnet in self.private_subnets()])

        # return [self.build_subnet_association(self.public_subnet_a(), self.public_route_table()),
        #         self.build_subnet_association(self.public_subnet_b(), self.public_route_table()),
        #         self.build_subnet_association(self.private_subnet_a(), self.private_route_table()),
        #         self.build_subnet_association(self.private_subnet_b(), self.private_route_table())]

    def db_security_group(self) -> SecurityGroup:
        """ Define the database security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id(C4NetworkExports.DB_SECURITY_GROUP, context='db_security_group')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows database access on a port range',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def db_security_group_output(self) -> Output:
        resource = self.db_security_group()
        export_name = C4NetworkExports.DB_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name, context='db_security_group_output')
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
        return output

    def db_inbound_rule(self) -> SecurityGroupIngress:
        """ Returns inbound rules for database (RDS) security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group-rule-1.html
        """
        logical_id = self.name.logical_id('DBPortRangeAccess', context='db_inbound_rule')
        return SecurityGroupIngress(
            logical_id,
            CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
            Description='allows database access on tcp ports 54xx',
            GroupId=Ref(self.db_security_group()),
            IpProtocol='tcp',
            FromPort=self.DB_PORT_LOW,
            ToPort=self.DB_PORT_HIGH,
        )

    def db_outbound_rule(self) -> SecurityGroupEgress:
        """ Returns outbound rules for database (RDS) security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-security-group-egress.html
        """
        logical_id = self.name.logical_id('DBOutboundAllAccess', context='db_outbound_rule')
        return SecurityGroupEgress(
            logical_id,
            CidrIp='0.0.0.0/0',  # TODO web sg w/ 'DestinationSecurityGroupId'
            Description='allows outbound traffic to tcp 54xx',
            GroupId=Ref(self.db_security_group()),
            IpProtocol='tcp',
            FromPort=self.DB_PORT_LOW,
            ToPort=self.DB_PORT_HIGH,
        )

    def https_security_group(self):
        """ Define the https-only web security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id('HTTPSSecurityGroup', context='https_security_group')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows https-only web access on port 443',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def https_security_group_output(self) -> Output:
        resource = self.https_security_group()
        export_name = C4NetworkExports.HTTPS_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name, context='https_security_group_output')
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
        return output

    def https_inbound_rule(self) -> SecurityGroupIngress:
        """ Returns inbound rules for https-only web security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group-rule-1.html
        """
        logical_id = self.name.logical_id('HTTPSInboundAccess', context='https_inbound_rule')
        return SecurityGroupIngress(
            logical_id,
            CidrIp='0.0.0.0/0',
            Description='allows inbound traffic on tcp port 443',
            GroupId=Ref(self.https_security_group()),
            IpProtocol='tcp',
            FromPort=443,
            ToPort=443,
        )

    def https_outbound_rule(self) -> SecurityGroupEgress:
        """ Returns outbound rules for https-only web security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-security-group-egress.html
        """
        logical_id = self.name.logical_id('HTTPSOutboundAllAccess', context='https_outbound_rule')
        return SecurityGroupEgress(
            logical_id,
            CidrIp='0.0.0.0/0',
            Description='allows outbound traffic on tcp port 443',
            GroupId=Ref(self.https_security_group()),
            IpProtocol='tcp',
            FromPort=443,
            ToPort=443,
        )

    def application_security_group(self) -> SecurityGroup:
        """ Returns application security group for rules needed by application to access resources. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id('ApplicationSecurityGroup', context='application_security_group')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows access needed by Application',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def application_security_group_output(self) -> Output:
        resource = self.application_security_group()
        export_name = C4NetworkExports.APPLICATION_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name, context='application_security_group_output')
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=self.EXPORTS.export(export_name),
        )
        return output

    def application_security_rules(self) -> [SecurityGroupIngress, SecurityGroupEgress]:
        """ Returns list of inbound and outbound rules needed by Application to access resources.

            These are each attached to the application_security_group, which is in turn attached to
            the virtual_private_cloud. The Application security group, when attached to a Application environment
            via an 'aws:autoscaling:launchconfiguration' option, then enable access to and from the application
            on specific ports via specific protocols. Ref:

            https://docs.aws.amazon.com/vpc/latest/userguide/VPC_SecurityGroups.html
        """
        return [
            SecurityGroupIngress(
                self.name.logical_id('ApplicationHTTPSInboundAccess', context='application_security_rules1'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundAllAccess', context='application_security_rules2'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationWebInboundAccess', context='application_security_rules3'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationWebOutboundAllAccess', context='application_security_rules4'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationNTPInboundAllAccess', context='application_security_rules5'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on udp port 123',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationNTPOutboundAllAccess', context='application_security_rules6'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on udp port 123',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess', context='application_security_rules7'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess', context='application_security_rules8'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 22',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
        ]

    def bastion_host(self):
        """ Defines a bastion host in public subnet a of the vpc. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/AWS_EC2.html
        """
        logical_id = self.name.logical_id('BastionHost')
        network_interface_logical_id = self.name.logical_id('BastionHostNetworkInterface', context='bastion_host')
        instance_name = self.name.instance_name('bastion-host')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=instance_name),
            ImageId='ami-0742b4e673072066f',
            InstanceType='t2.nano',
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=True,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group())],
                # SubnetId=Ref(self.public_subnet_a()),
                SubnetId=Ref(self.public_subnets()[0]),
            )],
            KeyName='trial-ssh-key-01',  # TODO parameterize
        )

    def create_vpc_interface_endpoint(self, identifier, service_name, dns=True) -> VPCEndpoint:
        """ Creates a (interface) VPC endpoint for the given service_name (in private subnets).
            This is to allow tasks running in private subnet to access needed AWS Services. See below explanation.
            https://stackoverflow.com/questions/61265108/aws-ecs-fargate-resourceinitializationerror-unable-to-pull-secrets-or-registry?noredirect=1&lq=1

            :param identifier: a name to be used in the logical ID for this VPC Interface Endpoint
            :param service_name: the aws service name for this endpoint, see aws ec2 describe-vpc-endpoint-services
            :param dns: boolean on whether or not to provide private DNS (must be disabled for s3)
        """
        # com.amazonaws.us-east-1.sqs -> sqs
        logical_id = self.name.logical_id(f'{identifier}VPCIEndpoint', context='create_vpc_interface_endpoint')
        return VPCEndpoint(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            VpcEndpointType='Interface',
            PrivateDnsEnabled=dns,
            ServiceName=service_name,
            # SubnetIds=[Ref(self.private_subnet_a()), Ref(self.private_subnet_b())],
            SubnetIds=[Ref(subnet) for subnet in self.private_subnets()],
            SecurityGroupIds=[Ref(self.application_security_group())]
        )

    def create_vpc_gateway_endpoint(self, identifier, service_name) -> VPCEndpoint:
        """ Creates a (gateway) VPC Endpoint for the given service_name (in private subnets).
            See notes on S3 and DynamoDB:
            https://docs.aws.amazon.com/vpc/latest/privatelink/vpc-endpoints.html

            :param identifier: a name to be used in the logical ID for this VPC Gateway Endpoint
            :param service_name: the aws service name for this endpoint, see aws ec2 describe-vpc-endpoint-services
        """
        logical_id = self.name.logical_id(f'{identifier}VPCGEndpoint', context='create_vpc_gateway_endpoint')
        return VPCEndpoint(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            VpcEndpointType='Gateway',
            ServiceName=service_name,
            RouteTableIds=[Ref(self.private_route_table())]
        )
