from troposphere import Ref, GetAtt, Output, Template
from troposphere.ec2 import (
    InternetGateway, Route, RouteTable, SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Subnet, SubnetRouteTableAssociation, VPC, VPCGatewayAttachment, NatGateway, EIP, Instance, NetworkInterfaceProperty,
    VPCEndpoint,
)
from src.part import C4Part
from src.exports import C4Exports
import logging


class C4NetworkExports(C4Exports):
    """ Helper class for working with network exported resources and their input values """
    VPC = 'ExportVPC'
    PRIVATE_SUBNET_A = 'ExportPrivateSubnetA'
    PRIVATE_SUBNET_B = 'ExportPrivateSubnetB'
    PUBLIC_SUBNET_A = 'ExportPublicSubnetA'
    PUBLIC_SUBNET_B = 'ExportPublicSubnetB'
    APPLICATION_SECURITY_GROUP = 'ExportApplicationSecurityGroup'  # XXX: Can we name this something more generic? -Will
    DB_SECURITY_GROUP = 'ExportDBSecurityGroup'
    HTTPS_SECURITY_GROUP = 'ExportHTTPSSecurityGroup'

    def __init__(self):
        parameter = 'NetworkStackNameParameter'
        # could perhaps reference C4NetworkPart.name.stack_name
        super().__init__(parameter)


class C4Network(C4Part):
    """ Note: when reading this code 'application' roughly refers to the AWS service running
        the CGAP Portal, whether it be Elastic Beanstalk or ECS.
    """

    # The theory in this choice is that this will give us up to 32 VPCs of 8 subnets each
    # (or some other more clever subdivision of these than is used for private_subnet_a and friends).
    # We imagine it's more likely we'll need extra VPCs than it is likely we'll need extra subnets.
    # It does not work to take 10.0.0.0/13 because 10.0 is reserved in some way.
    # Using 10.8.0.0/13 gives us 10.8.0.0 to 10.15.255.255.
    # Looks like it's required to be between /16 and /28.
    # -kmp&eb -8-Jun-2021
    CIDR_BLOCK = '10.0.0.0/16'
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

        # Add subnets
        public_subnet_a, public_subnet_b, \
        private_subnet_a, private_subnet_b = self.public_subnet_a(), self.public_subnet_b(), \
                                             self.private_subnet_a(), self.private_subnet_b()
        template.add_resource(public_subnet_a)
        template.add_resource(public_subnet_b)
        template.add_resource(private_subnet_a)
        template.add_resource(private_subnet_b)

        # Add subnet outputs
        for i in self.subnet_outputs():
            template.add_output(i)

        # Create NAT gateways
        public_a_nat_eip = self.nat_eip('PublicSubnetAEIP')
        public_a_nat_gateway = self.nat_gateway(public_a_nat_eip, public_subnet_a)
        template.add_resource(public_a_nat_eip)
        template.add_resource(public_a_nat_gateway)
        public_b_nat_eip = self.nat_eip('PublicSubnetBEIP')
        public_b_nat_gateway = self.nat_gateway(public_b_nat_eip, public_subnet_b)
        template.add_resource(public_b_nat_eip)
        template.add_resource(public_b_nat_gateway)

        # Add Internet Gateway to public route table, NAT Gateway to private route table
        # XXX: why is this only possible with public_a_nat_gateway?
        for i in [self.route_internet_gateway(),
                  self.route_nat_gateway(public_a_nat_gateway)]:
            template.add_resource(i)

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
        # Add VPC Endpoints for AWS Services (to reduce NAT Gateway charges)
        # NOTE: the service names vary by region, so this may need to be configurable
        # See: aws ec2 describe-vpc-endpoint-services
        template.add_resource(self.create_vpc_interface_endpoint('sqs',
                                                                 'com.amazonaws.us-east-1.sqs'))
        template.add_resource(self.create_vpc_interface_endpoint('s3',
                                                                 'com.amazonaws.us-east-1.s3',
                                                                 dns=False))
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

    def nat_eip(self, name) -> EIP:
        """ Define an Elastic IP for a NAT gateway. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-eip.html
        """
        logical_id = self.name.logical_id(name)
        return EIP(
            logical_id,
            Domain='vpc',
        )

    def nat_gateway(self, eip: EIP, subnet: Subnet) -> NatGateway:
        """ Define a NAT Gateway. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-natgateway.html
        """
        logical_id = self.name.logical_id(subnet.title)  # + 'NATGateway')
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

    def route_nat_gateway(self, public_subnet_nat_gateway: NatGateway):
        """ Defines NAT Gateway route to Private Route Table Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-ec2-route.html
        """
        logical_id = self.name.logical_id(public_subnet_nat_gateway.title)
        return Route(
            logical_id,
            RouteTableId=Ref(self.private_route_table()),
            DestinationCidrBlock='0.0.0.0/0',
            NatGatewayId=Ref(public_subnet_nat_gateway)
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
        """ Builds a subnet association between a subnet and a route table. What makes a 'public' subnet 'public'
            and a 'private' subnet 'private'. """
        logical_id = self.name.logical_id('{}To{}Association'.format(subnet.title, route_table.title))
        return SubnetRouteTableAssociation(
            logical_id,
            SubnetId=Ref(subnet),
            RouteTableId=Ref(route_table),
        )

    # NOTE: These CIDR IP ranges need to exist within the space defined by the CIDR_BLOCK class variable.
    #       To compute the implications of that, use a tool like https://www.ipaddressguide.com/cidr
    #
    #       Also, to succeed we have to expand the default number of EIPs from 5 to a larger number (100?)
    #       or we may get an error like:
    #         The maximum number of addresses has been reached.
    #         (Service: AmazonEC2; Status Code: 400; Error Code: AddressLimitExceeded; Request ID: <guid>; Proxy: null)

    def private_subnet_a(self) -> Subnet:
        """ Define private subnet A """
        return self.build_subnet('PrivateSubnetA', '10.0.0.0/20', self.virtual_private_cloud(),
                                 'us-east-1a')

    def public_subnet_a(self) -> Subnet:
        """ Define public subnet A """
        return self.build_subnet('PublicSubnetA', '10.0.16.0/20', self.virtual_private_cloud(), 'us-east-1a')

    def private_subnet_b(self) -> Subnet:
        """ Define private subnet B """
        return self.build_subnet('PrivateSubnetB', '10.0.32.0/20', self.virtual_private_cloud(),
                                 'us-east-1b')

    def public_subnet_b(self) -> Subnet:
        """ Define public subnet B """
        return self.build_subnet('PublicSubnetB', '10.0.48.0/20', self.virtual_private_cloud(), 'us-east-1b')

    def subnet_outputs(self) -> [Output]:
        """ Define outputs for all subnets, for cross-stack compatibility. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
        """
        subnet_exports = [
            (self.public_subnet_a(), C4NetworkExports.PUBLIC_SUBNET_A),
            (self.public_subnet_b(), C4NetworkExports.PUBLIC_SUBNET_B),
            (self.private_subnet_a(), C4NetworkExports.PRIVATE_SUBNET_A),
            (self.private_subnet_b(), C4NetworkExports.PRIVATE_SUBNET_B),
        ]
        outputs = []
        for subnet, export_name in subnet_exports:
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
        return [self.build_subnet_association(self.public_subnet_a(), self.public_route_table()),
                self.build_subnet_association(self.public_subnet_b(), self.public_route_table()),
                self.build_subnet_association(self.private_subnet_a(), self.private_route_table()),
                self.build_subnet_association(self.private_subnet_b(), self.private_route_table())]

    def db_security_group(self) -> SecurityGroup:
        """ Define the database security group. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id(C4NetworkExports.DB_SECURITY_GROUP)
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
        logical_id = self.name.logical_id(export_name)
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
        export_name = C4NetworkExports.HTTPS_SECURITY_GROUP
        logical_id = self.name.logical_id(export_name)
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

    def application_security_group(self) -> SecurityGroup:
        """ Returns application security group for rules needed by application to access resources. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-security-group.html
        """
        logical_id = self.name.logical_id('ApplicationSecurityGroup')
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
        logical_id = self.name.logical_id(export_name)
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
                self.name.logical_id('ApplicationHTTPSInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationWebInboundAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationWebOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationNTPInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on udp port 123',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationNTPOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on udp port 123',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='udp',
                FromPort=123,
                ToPort=123,
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess'),
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
        network_interface_logical_id = self.name.logical_id('BastionHostNetworkInterface')
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
                SubnetId=Ref(self.public_subnet_a()),
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
        logical_id = self.name.logical_id('%sVPCEndpoint' % identifier)
        return VPCEndpoint(
            logical_id,
            VpcId=Ref(self.virtual_private_cloud()),
            VpcEndpointType='Interface',
            PrivateDnsEnabled=dns,
            ServiceName=service_name,
            SubnetIds=[Ref(self.private_subnet_a()), Ref(self.private_subnet_b())],
            SecurityGroupIds=[Ref(self.application_security_group())]
        )
