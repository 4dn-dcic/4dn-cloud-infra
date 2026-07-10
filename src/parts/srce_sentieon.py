from troposphere import Ref
from troposphere.ec2 import SecurityGroupEgress, SecurityGroupIngress

from .sentieon import C4SentieonSupport
from .network import C4Network
from .srce_network import C4SRCENetworkExports
from ..base import ConfigManager
from ..constants import Settings


class C4SRCESentieonSupport(C4SentieonSupport):
    """
    SRCE variant of C4SentieonSupport. Deploys the Sentieon license server inside the
    IT-provided Application VPC (which has public subnets) by swapping in
    C4SRCENetworkExports. The server must be publicly accessible and reachable
    from the Compute VPC on port 8990 (license server).

    application_security_rules() is overridden to allow license server traffic
    from both the App VPC CIDR and the Compute VPC CIDR.
    """
    NETWORK_EXPORTS = C4SRCENetworkExports()

    STACK_NAME_TOKEN = 'srce-sentieon'
    STACK_TITLE_TOKEN = 'SRCESentieon'

    def application_security_rules(self) -> list:
        """Security rules for the Sentieon license server in the App VPC."""
        app_cidr = ConfigManager.get_config_setting(Settings.VPC_CIDR, default=C4Network.CIDR_BLOCK)
        compute_cidr = ConfigManager.get_config_setting(Settings.COMPUTE_VPC_CIDR, default=None)
        # SSH is restricted to the admin/VPN CIDR (config-driven, defaults to the App VPC CIDR),
        # never 0.0.0.0/0 — a world-open SSH port will not survive an IT security review for a
        # "secure enclave" (SEC-4).
        admin_cidr = ConfigManager.get_config_setting(Settings.SENTIEON_ADMIN_CIDR, default=app_cidr)
        rules = [
            # SSH Access — restricted to the admin/VPN CIDR (SEC-4).
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess'),
                CidrIp=admin_cidr,
                Description='allows inbound SSH (tcp/22) from the admin/VPN CIDR',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess'),
                CidrIp=admin_cidr,
                Description='allows outbound SSH (tcp/22) to the admin/VPN CIDR',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),

            # License Server — allow from App VPC
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSentieonServer'),
                CidrIp=app_cidr,
                Description='allows inbound traffic on tcp port 8990 from App VPC',
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

            # ICMP for server diagnostics — restricted to the App VPC CIDR, not world-open (SEC-4).
            SecurityGroupIngress(
                self.name.logical_id('ApplicationICMPInboundAllAccess'),
                CidrIp=app_cidr,
                FromPort=-1,
                ToPort=-1,
                Description='allows ICMP from within the App VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationICMPOutboundAllAccess'),
                CidrIp=app_cidr,
                FromPort=-1,
                ToPort=-1,
                Description='allows ICMP within the App VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='icmp',
            ),
        ]

        # License Server — allow from Compute VPC (cross-VPC)
        if compute_cidr:
            rules.append(SecurityGroupIngress(
                self.name.logical_id('SentieonFromComputeVPC'),
                CidrIp=compute_cidr,
                Description='allows inbound traffic on tcp port 8990 from Compute VPC',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=8990,
                ToPort=8990,
            ))

        return rules
