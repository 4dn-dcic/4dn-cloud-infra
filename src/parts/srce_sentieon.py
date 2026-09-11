import re

from awacs.aws import PolicyDocument, Statement, Action, Principal
from troposphere import Base64, Join, Parameter, Ref, Template
from troposphere.ec2 import (
    BlockDeviceMapping, EBSBlockDevice, Instance, NetworkInterfaceProperty,
    SecurityGroupEgress, SecurityGroupIngress,
)
from troposphere.iam import InstanceProfile, Role

from .sentieon import C4SentieonSupport
from .network import C4Network
from .srce_network import C4SRCENetworkExports
from ..base import ConfigManager
from ..constants import Settings


# An AMI ID is 'ami-' plus 8 (legacy) or 17 hex digits. Checked at synthesis time so a typo in
# config.json is a legible error here rather than an InvalidAMIID.Malformed rollback at deploy time.
AMI_ID_PATTERN = re.compile(r'^ami-(?:[0-9a-f]{8}|[0-9a-f]{17})$')


class C4SRCESentieonSupport(C4SentieonSupport):
    """
    SRCE variant of C4SentieonSupport: the Sentieon license server inside the IT-provided
    Application VPC.

    Differences from the standard stack, all of them required for a secure enclave:

    * **Application VPC private subnet, no public IP.** The enclave's Application VPC is not
      guaranteed to have public subnets at all, and the standard stack's
      ``ImportValue ${NetworkStackNameParameter}-PublicSubnetA`` therefore resolves to an export
      ``srce-network`` only publishes when ``public.subnets`` happens to be configured. The
      license server is reached from inside the enclave (the portal in the Application VPC and
      compute jobs in the Compute VPC), so it belongs on a private subnet.
    * **The AMI is configuration, not code** (``sentieon.ami_id``). The hardened image is issued
      per account by the institution's IT/security team; the standard stack's fallback to
      ``EC2Constants.DEFAULT_AMI_IMAGE`` is an AMI ID from one specific account and silently
      produces an undeployable (or wrong) instance anywhere else.
    * **SSM Session Manager is the operator access path**, since the instance has no public IP.
      That needs an instance profile on the instance and HTTPS egress that can reach the SSM
      endpoints -- both added here.
    * **Encrypted root volume**, which a secure enclave requires.

    The security rules allow license-server traffic (tcp/8990) from the Application VPC CIDR and,
    when ``compute.vpc.cidr`` is configured, from the Compute VPC CIDR.
    """
    NETWORK_EXPORTS = C4SRCENetworkExports()

    STACK_NAME_TOKEN = 'srce-sentieon'
    STACK_TITLE_TOKEN = 'SRCESentieon'

    # Nitro-based equivalent of the t2.nano Sentieon documents for a persistent license server;
    # override with 'sentieon.instance_type' if the supplied AMI needs a different family.
    DEFAULT_INSTANCE_TYPE = 't3.nano'
    DEFAULT_VOLUME_SIZE = 20
    ROOT_DEVICE_NAME = '/dev/xvda'

    def build_template(self, template: Template) -> Template:
        """ Same shape as the standard Sentieon stack, plus the instance profile the SSM access
            path needs. The base implementation is not reused because the instance must be added
            after the role it references.
        """
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))
        template.add_parameter(self.ssh_key())

        template.add_resource(self.application_security_group())
        for rule in self.application_security_rules():
            template.add_resource(rule)

        template.add_resource(self.instance_role())
        template.add_resource(self.instance_profile())
        template.add_resource(self.sentieon_license_server())

        template.add_output(self.output_sentieon_server_ip())

        return template

    # ---------------------------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------------------------

    @classmethod
    def ami_id(cls) -> str:
        """ The AMI the license server boots from, read from 'sentieon.ami_id'.

            Deliberately has no default. Every other SRCE input names something the institution
            provisioned (a VPC, a subnet, a CIDR) and this is no different: the hardened AMI is
            issued per account, and an AMI ID is meaningless in an account that does not own it.
            Falling back to EC2Constants.DEFAULT_AMI_IMAGE -- what the standard stack does -- would
            hardcode one account's image into every enclave deployment.
        """
        ami_id = ConfigManager.get_config_setting(Settings.SENTIEON_AMI_ID, default=None)
        if not ami_id:
            raise RuntimeError(
                f"{Settings.SENTIEON_AMI_ID!r} must be set in config.json to deploy"
                f" {cls.STACK_NAME_TOKEN}: the Sentieon license server's AMI is supplied per"
                f" account by the institution's IT/security team, so there is no default."
            )
        ami_id = str(ami_id).strip()
        if not AMI_ID_PATTERN.match(ami_id):
            raise RuntimeError(
                f"{Settings.SENTIEON_AMI_ID!r} is {ami_id!r}, which is not an AMI ID"
                f" ('ami-' followed by 8 or 17 hex digits)."
            )
        return ami_id

    @classmethod
    def instance_type(cls) -> str:
        return ConfigManager.get_config_setting(Settings.SENTIEON_INSTANCE_TYPE,
                                                default=cls.DEFAULT_INSTANCE_TYPE)

    @classmethod
    def volume_size(cls) -> int:
        return int(ConfigManager.get_config_setting(Settings.SENTIEON_VOLUME_SIZE,
                                                    default=cls.DEFAULT_VOLUME_SIZE))

    @classmethod
    def app_vpc_cidr(cls) -> str:
        return ConfigManager.get_config_setting(Settings.VPC_CIDR, default=C4Network.CIDR_BLOCK)

    # ---------------------------------------------------------------------------------------
    # Security groups
    # ---------------------------------------------------------------------------------------

    def application_security_rules(self) -> list:
        """Security rules for the Sentieon license server in the App VPC."""
        app_cidr = self.app_vpc_cidr()
        compute_cidr = ConfigManager.get_config_setting(Settings.COMPUTE_VPC_CIDR, default=None)
        # SSH is restricted to the admin/VPN CIDR (config-driven, defaults to the App VPC CIDR),
        # never 0.0.0.0/0 — a world-open SSH port will not survive an IT security review for a
        # "secure enclave".
        admin_cidr = ConfigManager.get_config_setting(Settings.SENTIEON_ADMIN_CIDR, default=app_cidr)
        rules = [
            # SSH Access — restricted to the admin/VPN CIDR.
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

            # Outbound HTTPS inside the App VPC. The instance has no public IP, so SSM Session
            # Manager (the operator access path) reaches ssm/ssmmessages/ec2messages through the
            # Application VPC's interface endpoints, which answer on 443 at in-VPC addresses.
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundVPC'),
                CidrIp=app_cidr,
                Description='allows outbound tcp/443 within the App VPC (SSM interface endpoints)',
                GroupId=Ref(self.application_security_group()),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),

            # ICMP for server diagnostics — restricted to the App VPC CIDR, not world-open.
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

    # ---------------------------------------------------------------------------------------
    # IAM
    # ---------------------------------------------------------------------------------------

    def instance_role(self) -> Role:
        """ Instance role for the license server.

            Held by this stack rather than the shared ``iam`` stack: ``iam`` is an
            ecosystem-shared stack consumed unchanged by the existing deployments (see
            tests/test_fixed_stack_parity.py), and this role exists only for as long as this
            stack does.

            AmazonSSMManagedInstanceCore is the whole grant. It is what Session Manager requires,
            and Session Manager is the only way onto an instance that has no public IP and whose
            SSH ingress is limited to the institutional admin CIDR.
        """
        return Role(
            self.name.logical_id('SentieonInstanceRole'),
            AssumeRolePolicyDocument=PolicyDocument(
                Version='2012-10-17',
                Statement=[Statement(
                    Effect='Allow',
                    Action=[Action('sts', 'AssumeRole')],
                    Principal=Principal('Service', 'ec2.amazonaws.com'))
                ]
            ),
            ManagedPolicyArns=[
                'arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore',
            ],
            Tags=self.tags.cost_tag_array(name=self.name.logical_id('SentieonInstanceRole')),
        )

    def instance_profile(self) -> InstanceProfile:
        """ Instance profile wrapping the above role, attached to the license server. """
        return InstanceProfile(
            self.name.logical_id('SentieonInstanceProfile'),
            Roles=[Ref(self.instance_role())]
        )

    # ---------------------------------------------------------------------------------------
    # Compute
    # ---------------------------------------------------------------------------------------

    def bootstrap_user_data(self) -> list:
        """ Bootstrap for the license server.

            Mechanical only: bring up the SSM agent (so an operator can get on the box at all) and
            lay down the directory the licence daemon is installed into. The licence file itself is
            issued by Sentieon per server and cannot be baked into a template -- see the manual
            steps in docs/source/deploy_srce.rst and
            https://support.sentieon.com/appnotes/license_server/
        """
        return [
            '#!/bin/bash -xe\n',
            'systemctl enable amazon-ssm-agent || true\n',
            'systemctl start amazon-ssm-agent || true\n',
            'mkdir -p /opt/sentieon/license\n',
            'chmod 0750 /opt/sentieon/license\n',
        ]

    def root_block_device(self) -> BlockDeviceMapping:
        """ Encrypted gp3 root volume; an unencrypted volume does not belong in a secure enclave. """
        return BlockDeviceMapping(
            DeviceName=self.ROOT_DEVICE_NAME,
            Ebs=EBSBlockDevice(
                VolumeSize=self.volume_size(),
                VolumeType='gp3',
                Encrypted=True,
                DeleteOnTermination=True,
            )
        )

    def sentieon_license_server(self) -> Instance:
        """ The license server, in an Application VPC *private* subnet with no public IP.

            Note ``self.NETWORK_EXPORTS.PRIVATE_SUBNETS[0]``, not
            ``C4NetworkExports.PRIVATE_SUBNETS[0]``: the SRCE exports resolve the subnet export
            names from the configured ``private.subnets`` and raise when that key is unset, so an
            unconfigured deployment fails here at synthesis instead of emitting an ImportValue for
            an export ``srce-network`` never published.
        """
        logical_id = self.name.logical_id('SentieonLicenseServer')
        network_interface_logical_id = self.name.logical_id('SentieonLicenseServerNetworkInterface')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id),
            ImageId=self.ami_id(),
            InstanceType=self.instance_type(),
            IamInstanceProfile=Ref(self.instance_profile()),
            BlockDeviceMappings=[self.root_block_device()],
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=False,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group())],
                SubnetId=self.NETWORK_EXPORTS.import_value(self.NETWORK_EXPORTS.PRIVATE_SUBNETS[0]),
            )],
            KeyName=Ref(self.ssh_key()),
            UserData=Base64(Join('', self.bootstrap_user_data())),
            # GroupSet only orders the instance after the security group, not after its rules, and
            # the bootstrap above needs egress the moment the instance boots.
            DependsOn=[rule.title for rule in self.application_security_rules()],
        )
