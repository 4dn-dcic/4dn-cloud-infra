from troposphere import GetAtt, Join, Output, Ref, Template, Parameter
from troposphere.ec2 import (
    SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Instance, NetworkInterfaceProperty,
)
from dcicutils.cloudformation_utils import camelize
from ..exports import C4Exports
from ..part import C4Part
from ..base import ConfigManager, Settings
from .network import C4NetworkExports, C4Network

# dmichaels/20220705: Added to set AWS Outputs value for Sentieon server IP; similar to ecs.py for DNSName.
class C4SentieonSupportExports(C4Exports):
    """ Holds Sentieon export metadata. """

    @classmethod
    def output_sentieon_server_ip_key(cls, env_name):
        return f"SentieonServerIP{camelize(env_name)}"

    @classmethod
    def get_sentieon_server_ip(cls, env_name):
        sentieon_server_ip_key = cls.output_sentieon_server_ip_key(env_name)
        sentieon_server_ip = ConfigManager.find_stack_output(sentieon_server_ip_key, value_only=True)
        return sentieon_server_ip


class C4SentieonSupport(C4Part):
    """
    Layer that provides an EC2 and associated resources for a Sentieon license server
    """
    SENTIEON_MASTER_CIDR = '52.89.132.242/32'
    STACK_NAME_TOKEN = 'sentieon'
    STACK_TITLE_TOKEN = 'Sentieon'
    NETWORK_EXPORTS = C4NetworkExports()

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # SSH Key for access
        template.add_parameter(self.ssh_key())

        # Security Group
        template.add_resource(self.application_security_group())
        for rule in self.application_security_rules():
            template.add_resource(rule)

        # Add server
        template.add_resource(self.sentieon_license_server())

        # Add outputs
        template.add_output(self.output_sentieon_server_ip())

        return template

    @staticmethod
    def ssh_key() -> Parameter:
        """
        Parameter for the ssh key to associate with the Sentieon License Server
        """
        return Parameter(
            'SentieonSSHKey',
            Description='SSH Key to use with Sentieon - must be created ahead of time',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.SENTIEON_SSH_KEY)
        )

    def application_security_group(self) -> SecurityGroup:
        """ Builds the application security group for the Sentieon License Server. """
        logical_id = self.name.logical_id('SentieonSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows access needed by Sentieon License Server',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def application_security_rules(self) -> [SecurityGroupIngress, SecurityGroupEgress]:
        """ Builds the actual rules associated with the above SG. """
        return [
            # SSH Access
            # TODO: maybe only manually add this, so "my IP" restriction can be used? - Will Oct 27 2021
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
                CidrIp=C4Network.CIDR_BLOCK,
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
                FromPort=-1,
                ToPort=-1,
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
            SecurityGroupIngress(
                self.name.logical_id('ApplicationICMPv6InboundAllAccess'),
                CidrIp='0.0.0.0/0',
                FromPort=-1,
                ToPort=-1,
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmpv6',
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationICMPOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                FromPort=-1,
                ToPort=-1,
                Description='allows ICMP',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
        ]

    def sentieon_license_server(self) -> Instance:
        """ Builds an EC2 Instance for use with Sentieon. Requires some manual setup,
            see: https://support.sentieon.com/appnotes/license_server/#amazon-web-services-running-a-license-server-in-a-persistent-t2-nano-instance
        """
        logical_id = self.name.logical_id('SentieonLicenseServer')
        network_interface_logical_id = self.name.logical_id('SentieonLicenseServerNetworkInterface')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id),
            ImageId=ConfigManager.get_config_setting(Settings.HMS_SECURE_AMI, default='ami-087c17d1fe0178315'),  # amzn2-ami-hvm-2.0.20210813.1-x86_64-gp2
            InstanceType='t2.nano',
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=True,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group())],
                SubnetId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNETS[0]),
            )],
            KeyName=Ref(self.ssh_key())
        )

    # dmichaels/20220705: Added to set AWS Outputs value for Sentieon server IP; similar to ecs.py for DNSName.
    def output_sentieon_server_ip(self, env=None) -> Output:
        """ Outputs URL to access portal. """
        env = env or ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Output(
            C4SentieonSupportExports.output_sentieon_server_ip_key(env),
            Description='IP of Sentieon EC2 Server.',
            Value=GetAtt(self.sentieon_license_server(), 'PrivateIp')
        )
