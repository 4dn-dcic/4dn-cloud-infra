from troposphere import Ref, GetAtt, Output, Template, Parameter
from troposphere.ec2 import (
    InternetGateway, Route, RouteTable, SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Subnet, SubnetRouteTableAssociation, VPC, VPCGatewayAttachment, NatGateway, EIP, Instance, NetworkInterfaceProperty,
    VPCEndpoint,
)
from ..part import C4Part


class C4SentieonSupport(C4Part):
    """
    Layer that provides an EC2 and associated resources for a Sentieon license server
    """
    SENTIEON_MASTER_CIDR = '52.89.132.242/32'
    STACK_NAME_TOKEN = "sentieon"
    STACK_TITLE_TOKEN = "Sentieon"

    def build_template(self, template: Template) -> Template:
        # Parameters
        template.add_parameter(self.vpc_id())
        template.add_parameter(self.vpc_cidr())
        template.add_parameter(self.ssh_key())
        template.add_parameter(self.subnet_a())

        # Security Group
        template.add_resource(self.application_security_group())
        for rule in self.application_security_rules():
            template.add_resource(rule)

        # Add server
        template.add_resource(self.sentieon_license_server())

        return template

    @staticmethod
    def vpc_id() -> Parameter:
        """ Parameter for the VPC ID. """
        return Parameter(
            'SentieonVPCID',
            Description='VPC ID to associate with Sentieon SG',
            Type='String',
        )

    @staticmethod
    def vpc_cidr() -> Parameter:
        """
        Parameter for the vpc CIDR block we would like to deploy to
        """
        return Parameter(
            'SentieonTargetCIDR',
            Description='CIDR block for VPC',
            Type='String',
        )

    @staticmethod
    def subnet_a() -> Parameter:
        """
        Parameter for the subnet we would like to deploy to
        """
        return Parameter(
            'SentieonTargetSubnet',
            Description='Subnet to deploy Sentieon license server to',
            Type='String',
        )

    @staticmethod
    def ssh_key() -> Parameter:
        """
        Parameter for the ssh key to associate with the Sentieon License Server
        """
        return Parameter(
            'SentieonSSHKey',
            Description='SSH Key to use with Sentieon - must be created ahead of time',
            Type='String',
        )

    def application_security_group(self) -> SecurityGroup:
        """ Builds the application security group for the Sentieon License Server. """
        logical_id = self.name.logical_id('SentieonSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows access needed by Sentieon License Server',
            VpcId=Ref(self.vpc_id()),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def application_security_rules(self) -> [SecurityGroupIngress, SecurityGroupEgress]:
        """ Builds the actual rules associated with the above SG. """
        return [
            # SSH Access
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

            # License Server
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSentieonServer'),
                CidrIp=Ref(self.vpc_cidr()),
                Description='allows inbound traffic on tcp port 8990 (license server port)',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=8990,
                ToPort=8990,
            ),

            # Outbound HTTPS to license master
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundAllAccess'),
                CidrIp=self.SENTIEON_MASTER_CIDR,
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),

            # Various ICMP for server
            SecurityGroupIngress(
                self.name.logical_id('ApplicationICMPInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationICMPv6InboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmpv6',
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationICMPOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
        ]

    def sentieon_license_server(self):
        """ Builds an EC2 Instance for use with Sentieon. Requires some manual setup,
            see: https://support.sentieon.com/appnotes/license_server/#amazon-web-services-running-a-license-server-in-a-persistent-t2-nano-instance
        """
        logical_id = self.name.logical_id('SentieonLicenseServer')
        network_interface_logical_id = self.name.logical_id('SentieonLicenseServerNetworkInterface')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id),
            ImageId='ami-087c17d1fe0178315',  # amzn2-ami-hvm-2.0.20210813.1-x86_64-gp2
            InstanceType='t2.nano',
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=True,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group())],
                SubnetId=Ref(self.subnet_a()),
            )],
            KeyName=Ref(self.ssh_key())
        )
