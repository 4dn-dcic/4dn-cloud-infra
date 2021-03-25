from troposphere import Ref, GetAtt, Export, Output, Sub, Template, ImportValue
from troposphere.ec2 import (
    InternetGateway, LocalGatewayRoute, Route, RouteTable, SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Subnet, SubnetCidrBlock, SubnetRouteTableAssociation, Tag, VPC, VPCGatewayAttachment, NatGateway, EIP, Instance
)
from src.exceptions import C4NetworkException
from src.part import QCPart
import logging


class QCNetworkExports:
    """ Helper class for working with network exported resources and their input values """
    REFERENCE_PARAM_KEY = 'NetworkStackNameParameter'
    REFERENCE_PARAM = '${' + REFERENCE_PARAM_KEY + '}'
    # could perhaps reference QCNetworkPart.name.stack_name
    STACK_NAME_PARAM = '${AWS::StackName}'
    VPC = 'ExportVPC'
    PRIVATE_SUBNET_A = 'ExportPrivateSubnetA'
    PRIVATE_SUBNET_B = 'ExportPrivateSubnetB'
    PUBLIC_SUBNET_A = 'ExportPublicSubnetA'
    PUBLIC_SUBNET_B = 'ExportPublicSubnetB'
    BEANSTALK_SECURITY_GROUP = 'ExportBeanstalkSecurityGroup'
    DB_SECURITY_GROUP = 'ExportDBSecurityGroup'
    HTTPS_SECURITY_GROUP = 'ExportHTTPSSecurityGroup'

    @classmethod
    def export(cls, resource_id):
        """ Helper method for building the Export field in an Output for a template. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        # valid exports: [i for i in dir(QCNetworkExports) if i.isupper() and 'PARAM' not in i]
        return Export(Sub(
            '{}-{}'.format(cls.STACK_NAME_PARAM, resource_id)
        ))

    @classmethod
    def import_value(cls, resource_id):
        """ Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-importvalue.html
        """
        # valid import values: [i for i in dir(QCNetworkExports) if i.isupper() and 'PARAM' not in i]
        return ImportValue(Sub(
            '{}-{}'.format(cls.REFERENCE_PARAM, resource_id)
        ))


class QCNetwork(QCPart):
    CIDR_BLOCK = '10.2.0.0/16'
    DB_PORT_LOW = 5400
    DB_PORT_HIGH = 5499

    def build_template(self, template: Template) -> Template:
        """ Add network resources to template """
        logging.debug('Adding network resources to template')

        # Create Internet Gateway, VPC, and attach Internet Gateway to VPC.
        for i in [self.internet_gateway(), self.virtual_private_cloud(), self.internet_gateway_attachment()]:
            template.add_resource(i)
        # Add VPC output
        template.add_output(self.output_virtual_private_cloud())

        # Create NAT gateway
        for i in [self.nat_eip(), self.nat_gateway()]:
            template.add_resource(i)

        # Add route tables
        for i in [self.main_route_table(), self.private_route_table(), self.public_route_table()]:
            template.add_resource(i)

        # Add Internet Gateway to public route table, NAT Gateway to private route table
        for i in [self.route_internet_gateway(), self.route_nat_gateway()]:
            template.add_resource(i)

        # Add subnets
        for i in [self.public_subnet_a(), self.public_subnet_b(), self.private_subnet_a(), self.private_subnet_b()]:
            template.add_resource(i)
        # Add subnet outputs
        for i in self.subnet_outputs():
            template.add_output(i)

        # Add subnet-to-route-table associations
        for i in self.subnet_associations():
            template.add_resource(i)

        # Add security groups
        for i in [self.db_security_group(), self.https_security_group(), self.beanstalk_security_group()]:
            template.add_resource(i)
        # Add security group outputs
        for i in [self.db_security_group_output(), self.https_security_group_output(),
                  self.beanstalk_security_group_output()]:
            template.add_output(i)

        # Add db inbound and outbound rules
        for i in [self.db_inbound_rule(), self.db_outbound_rule()]:
            template.add_resource(i)

        # Add https inbound and outbound rules
        for i in [self.https_inbound_rule(), self.https_outbound_rule()]:
            template.add_resource(i)

        # Add beanstalk security rules
        for i in self.beanstalk_security_rules():
            template.add_resource(i)

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
        )

    def output_virtual_private_cloud(self) -> Output:
        """ Define output for VPC resource for cross-stack compatibility. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        export_name = QCNetworkExports.VPC
        logical_id = self.name.logical_id(export_name)
        resource = self.virtual_private_cloud()
        output = Output(
            logical_id,
            Value=Ref(self.virtual_private_cloud()),
            Export=QCNetworkExports.export(export_name),
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

    def nat_eip(self) -> EIP:
        """ Define an Elastic IP for a NAT gateway. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-eip.html
        """
        logical_id = self.name.logical_id('NatPublicIP')
        return EIP(
            logical_id,
            Domain='vpc',
        )

    def nat_gateway(self) -> NatGateway:
        """ Define a NAT Gateway. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-natgateway.html
        """
        logical_id = self.name.logical_id('NatGateway')
        return NatGateway(
            logical_id,
            DependsOn=self.nat_eip().title,
            AllocationId=GetAtt(self.nat_eip(), 'AllocationId'),
            SubnetId=Ref(self.public_subnet_a()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def main_route_table(self):
        """ Define main (default) route table resource Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
            TODO(berg) add local gateway association """
        logical_id = self.name.logical_id('MainRouteTable')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def private_route_table(self):
        """ Define route table resource *without* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        logical_id = self.name.logical_id('PrivateRouteTable')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def public_route_table(self):
        """ Define route table resource *with* an internet gateway attachment Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route-table.html
        """
        logical_id = self.name.logical_id('PublicRouteTable')
        return RouteTable(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def route_internet_gateway(self):
        """ Defines Internet Gateway route to Public Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        logical_id = self.name.logical_id('InternetGatewayRoute')
        return Route(
            logical_id,
            RouteTableId=Ref(self.public_route_table()),
            GatewayId=Ref(self.internet_gateway()),
            DestinationCidrBlock='0.0.0.0/0',
            # DependsOn -- TODO needed? see example in src/beanstalk.py
        )

    def route_nat_gateway(self):
        """ Defines NAT Gateway route to Private Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        logical_id = self.name.logical_id('NatGatewayRoute')
        return Route(
            logical_id,
            RouteTableId=Ref(self.private_route_table()),
            DestinationCidrBlock='0.0.0.0/0',
            NatGatewayId=Ref(self.nat_gateway())
            # DependsOn -- TODO needed? see example in src/beanstalk.py
        )

    def build_subnet(self, subnet_name, cidr_block, vpc, az) -> Subnet:
        """ Builds a subnet with given name, cidr_block strings, vpc resource, and availability zone (az). """
        logical_id = self.name.logical_id(subnet_name)
        return Subnet(
            logical_id,
            CidrBlock=cidr_block,
            VpcId=Ref(vpc),
            AvailabilityZone=az,
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def build_subnet_association(self, subnet, route_table) -> SubnetRouteTableAssociation:
        """ Builds a subnet assoociation between a subnet and a route table. What makes a 'public' subnet 'public'
            and a 'private' subnet 'private'. """
        logical_id = self.name.logical_id('{}To{}Association'.format(subnet.title, route_table.title))
        return SubnetRouteTableAssociation(
            logical_id,
            SubnetId=Ref(subnet),
            RouteTableId=Ref(route_table),
        )

    def public_subnet_a(self) -> Subnet:
        """ Define public subnet A """
        return self.build_subnet('PublicSubnetA', '10.2.5.0/24', self.virtual_private_cloud(), 'us-east-1a')

    def public_subnet_b(self) -> Subnet:
        """ Define public subnet B """
        return self.build_subnet('PublicSubnetB', '10.2.7.0/24', self.virtual_private_cloud(), 'us-east-1b')

    def private_subnet_a(self) -> Subnet:
        """ Define private subnet A """
        return self.build_subnet('PrivateSubnetA', '10.2.6.0/24', self.virtual_private_cloud(),
                                 'us-east-1a')

    def private_subnet_b(self) -> Subnet:
        """ Define private subnet B """
        return self.build_subnet('PrivateSubnetB', '10.2.8.0/24', self.virtual_private_cloud(),
                                 'us-east-1b')

    def subnet_outputs(self) -> [Output]:
        """ Define outputs for all subnets, for cross-stack compatibility. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        subnet_exports = [
            (self.public_subnet_a(), QCNetworkExports.PUBLIC_SUBNET_A),
            (self.public_subnet_b(), QCNetworkExports.PUBLIC_SUBNET_B),
            (self.private_subnet_a(), QCNetworkExports.PRIVATE_SUBNET_A),
            (self.private_subnet_b(), QCNetworkExports.PRIVATE_SUBNET_B),
        ]
        outputs = []
        for subnet, export_name in subnet_exports:
            logical_id = self.name.logical_id(export_name)
            output = Output(
                logical_id,
                Value=Ref(subnet),
                Export=QCNetworkExports.export(export_name),
            )
            outputs.append(output)
        return outputs

    def subnet_associations(self) -> [SubnetRouteTableAssociation]:
        """ Define a list of subnet associations, which can be unrolled and added to a template. """
        return [self.build_subnet_association(self.public_subnet_a(), self.public_route_table()),
                self.build_subnet_association(self.public_subnet_b(), self.public_route_table()),
                self.build_subnet_association(self.private_subnet_a(), self.private_route_table()),
                self.build_subnet_association(self.private_subnet_b(), self.private_route_table())]

    def db_security_group(self) -> SecurityGroup:
        """ Define the database security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id(QCNetworkExports.DB_SECURITY_GROUP)
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows database access on a port range',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def db_security_group_output(self) -> Output:
        resource = self.db_security_group()
        export_name = QCNetworkExports.DB_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name)
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=QCNetworkExports.export(export_name),
        )
        return output

    def db_inbound_rule(self) -> SecurityGroupIngress:
        """ Returns inbound rules for database (RDS) security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group-rule-1.html
        """
        logical_id = self.name.logical_id('DBPortRangeAccess')
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
        logical_id = self.name.logical_id('DBOutboundAllAccess')
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
        logical_id = self.name.logical_id('HTTPSSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows https-only web access on port 443',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def https_security_group_output(self) -> Output:
        resource = self.https_security_group()
        export_name = QCNetworkExports.HTTPS_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name)
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=QCNetworkExports.export(export_name),
        )
        return output


    def https_inbound_rule(self) -> SecurityGroupIngress:
        """ Returns inbound rules for https-only web security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group-rule-1.html
        """
        logical_id = self.name.logical_id('HTTPSInboundAccess')
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
        logical_id = self.name.logical_id('HTTPSOutboundAllAccess')
        return SecurityGroupEgress(
            logical_id,
            CidrIp='0.0.0.0/0',
            Description='allows outbound traffic on tcp port 443',
            GroupId=Ref(self.https_security_group()),
            IpProtocol='tcp',
            FromPort=443,
            ToPort=443,
        )

    def beanstalk_security_group(self) -> SecurityGroup:
        """ Returns beanstalk security group for rules needed by beanstalk to access resources. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id('BeanstalkSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows access needed by Beanstalk Application',
            VpcId=Ref(self.virtual_private_cloud()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def beanstalk_security_group_output(self) -> Output:
        resource = self.beanstalk_security_group()
        export_name = QCNetworkExports.BEANSTALK_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name)
        output = Output(
            logical_id,
            Value=Ref(resource),
            Export=QCNetworkExports.export(export_name),
        )
        return output

    def beanstalk_security_rules(self) -> [SecurityGroupIngress, SecurityGroupEgress]:
        """ Returns list of inbound and outbound rules needed by beanstalk to access resources.

            These are each attached to the beanstalk_security_group, which is in turn attached to
            the virtual_private_cloud. The beanstalk security group, when attached to a Beanstalk environment
            via an 'aws:autoscaling:launchconfiguration' option, then enable access to and from the application
            on specific ports via specific protocols. Ref:

            https://docs.aws.amazon.com/vpc/latest/userguide/VPC_SecurityGroups.html
        """
        return [
            SecurityGroupIngress(
                self.name.logical_id('BeanstalkHTTPSInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('BeanstalkHTTPSOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupIngress(
                self.name.logical_id('BeanstalkWebInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('BeanstalkWebOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupIngress(
                self.name.logical_id('BeanstalkNTPInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on udp port 123',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupEgress(
                self.name.logical_id('BeanstalkNTPOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on udp port 123',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupIngress(
                self.name.logical_id('BeanstalkSSHInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('BeanstalkSSHOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 22',
                GroupId=Ref(self.beanstalk_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
        ]

    def bastion_host(self):
        """ TODO: Defines a bastion host in public subnet a of the vpc """
        pass
