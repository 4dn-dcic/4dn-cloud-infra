from troposphere import Ref
from troposphere.ec2 import SecurityGroupEgress, SecurityGroupIngress

from .sentieon import C4SentieonSupport
from .network import C4Network, C4NetworkExports
from .scre_network import C4SCRENetworkExports
from ..base import ConfigManager
from ..constants import Settings


class C4SCRESentieonSupport(C4SentieonSupport):
    """
    SCRE variant of C4SentieonSupport. Deploys the Sentieon license server inside an
    IT-provided VPC by swapping in C4SCRENetworkExports.

    application_security_rules() is overridden to use a config-driven VPC CIDR
    (vpc.cidr) for the license server port rule instead of the hardcoded C4Network.CIDR_BLOCK.

    All other EC2 instance and security group logic is inherited unchanged.
    """
    NETWORK_EXPORTS = C4SCRENetworkExports()

    STACK_NAME_TOKEN = 'scre-sentieon'
    STACK_TITLE_TOKEN = 'SCRESentieon'

    def application_security_rules(self) -> list:
        """Security rules for the Sentieon license server, using config-provided VPC CIDR."""
        cidr = ConfigManager.get_config_setting(Settings.VPC_CIDR, default=C4Network.CIDR_BLOCK)
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

            # License Server — use config CIDR instead of hardcoded C4Network.CIDR_BLOCK
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSentieonServer'),
                CidrIp=cidr,
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
