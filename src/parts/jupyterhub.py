from troposphere import Ref, Template, Parameter
from troposphere.ec2 import (
    SecurityGroup, SecurityGroupEgress, SecurityGroupIngress,
    Instance, NetworkInterfaceProperty,
)
from ..part import C4Part
from ..base import ConfigManager, Settings
from .network import C4NetworkExports, C4Network


class C4JupyterHubSupport(C4Part):
    """
    Layer that provides a Load Balancer + EC2 instance for running our Dockerized JH component.
    """
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_HUB_SIZE = 'c5.large'

    def build_template(self, template: Template) -> Template:
        # Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # SSH Key for access
        template.add_parameter(self.ssh_key())

        # TODO: ACM certificate parameter?

        # Security Group
        template.add_resource(self.application_security_group())
        for rule in self.application_security_rules():
            template.add_resource(rule)

        # JupyterHub
        template.add_resource(self.jupyterhub())

        # TODO: Load balancer
        return template

    @staticmethod
    def ssh_key() -> Parameter:
        """
        Parameter for the ssh key to associate with JH
        """
        return Parameter(
            'JHSSHKey',
            Description='SSH Key to use with JH - must be created ahead of time',
            Type='String',
            Default=ConfigManager.get_config_setting(Settings.JH_SSH_KEY)
        )

    def application_security_group(self) -> SecurityGroup:
        """ Builds the application security group for the Sentieon License Server. """
        logical_id = self.name.logical_id('JHSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription='allows access needed by Jupyterhub',
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

            # HTTP to/from LB
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows outbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),

            # HTTPS to/from LB
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
        ]

    def jupyterhub(self) -> Instance:
        """ Builds an EC2 Instance for Jupyterhub """
        logical_id = self.name.logical_id('SentieonLicenseServer')
        network_interface_logical_id = self.name.logical_id('SentieonLicenseServerNetworkInterface')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id),
            ImageId=ConfigManager.get_config_setting(Settings.HMS_SECURE_AMI, default='ami-087c17d1fe0178315'),  # amzn2-ami-hvm-2.0.20210813.1-x86_64-gp2
            InstanceType=ConfigManager.get_config_setting(Settings.JH_INSTANCE_SIZE, default=self.DEFAULT_HUB_SIZE),
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=True,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group())],
                SubnetId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNETS[0]),
            )],
            KeyName=Ref(self.ssh_key())
        )
