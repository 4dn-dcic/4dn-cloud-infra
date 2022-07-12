from troposphere import (
    Ref, Parameter, Join,
    elasticloadbalancingv2 as elbv2,
    Base64
)
from troposphere.ec2 import (
    SecurityGroup, SecurityGroupEgress, SecurityGroupIngress, SecurityGroupRule,
    Instance, NetworkInterfaceProperty,
)
from ..part import C4Part
from ..base import ConfigManager, Settings
from .network import C4NetworkExports, C4Network


class C4EC2Common(C4Part):
    """
    Layer that provides general components for building a web app on EC2:
        * SSH Key
        * Security Group + Rules for instance and LB
        * EC2 Instance
        * Load Balancer
        * Target Group
    """
    NETWORK_EXPORTS = C4NetworkExports()
    DEFAULT_INSTANCE_SIZE = 'c5.large'

    @staticmethod
    def ssh_key(*, identifier, default) -> Parameter:
        """
        Parameter for the ssh key to associate with JH
        """
        return Parameter(
            f'{identifier}SSHKey',
            Description=f'SSH Key to use with {identifier} - must be created ahead of time',
            Type='String',
            Default=default
        )

    def application_security_group(self, *, identifier) -> SecurityGroup:
        """ Builds the application security group for the Sentieon License Server. """
        logical_id = self.name.logical_id(f'{identifier}SecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupName=logical_id,
            GroupDescription=f'allows access needed by {identifier}',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array(name=logical_id),
        )

    def application_security_rules(self, *, identifier) -> [SecurityGroupIngress, SecurityGroupEgress]:
        """ Builds the actual rules associated with the above SG. """
        return [
            # SSH Access
            # TODO: maybe only manually add this, so "my IP" restriction can be used? - Will Oct 27 2021
            SecurityGroupIngress(
                self.name.logical_id('ApplicationSSHInboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows inbound traffic on tcp port 22',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationSSHOutboundAllAccess'),
                CidrIp='0.0.0.0/0',
                Description='allows outbound traffic on tcp port 22',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=22,
                ToPort=22,
            ),

            # HTTP to/from LB
            SecurityGroupIngress(
                self.name.logical_id('ApplicationHTTPInboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows inbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPOutboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows outbound traffic on tcp port 80',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=80,
                ToPort=80,
            ),

            # HTTPS to/from LB
            SecurityGroupIngress(
                self.name.logical_id('ApplicationHTTPSInboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows inbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
            SecurityGroupEgress(
                self.name.logical_id('ApplicationHTTPSOutboundAllAccess'),
                CidrIp=C4Network.CIDR_BLOCK,
                Description='allows outbound traffic on tcp port 443',
                GroupId=Ref(self.application_security_group(identifier=identifier)),
                IpProtocol='tcp',
                FromPort=443,
                ToPort=443,
            ),
        ]

    def ec2_instance(self, *, identifier, instance_size, default_key, user_data=['']) -> Instance:
        """ Builds an EC2 instance for use with the application """
        logical_id = self.name.logical_id(f'{identifier}')
        network_interface_logical_id = self.name.logical_id(f'{identifier}NetworkInterface')
        return Instance(
            logical_id,
            Tags=self.tags.cost_tag_array(name=logical_id),
            ImageId=ConfigManager.get_config_setting(Settings.HMS_SECURE_AMI, default='ami-087c17d1fe0178315'),
            # amzn2-ami-hvm-2.0.20210813.1-x86_64-gp2
            InstanceType=ConfigManager.get_config_setting(instance_size, default=self.DEFAULT_INSTANCE_SIZE),
            NetworkInterfaces=[NetworkInterfaceProperty(
                network_interface_logical_id,
                AssociatePublicIpAddress=True,
                DeviceIndex=0,
                GroupSet=[Ref(self.application_security_group(identifier=identifier))],
                SubnetId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNETS[0]),
            )],
            KeyName=Ref(self.ssh_key(identifier=identifier, default=default_key)),
            UserData=Base64(Join('', user_data))
        )

    def lb_security_group(self, *, identifier) -> SecurityGroup:
        """ SG for the LB, allowing inbound traffic on ports 80/443 and outbound traffic on
            80/443 to the VPC. """
        logical_id = self.name.logical_id(f'{identifier}LBSecurityGroup')
        return SecurityGroup(
            logical_id,
            GroupDescription=f'Web load balancer security group for {identifier}.',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=443,
                    ToPort=443,
                    CidrIp='0.0.0.0/0',
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=80,
                    ToPort=80,
                    CidrIp='0.0.0.0/0',
                ),
            ],
            SecurityGroupEgress=[
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=443,
                    ToPort=443,
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
                SecurityGroupRule(
                    IpProtocol='tcp',
                    FromPort=80,
                    ToPort=80,
                    CidrIp=C4Network.CIDR_BLOCK,
                ),
            ],
            Tags=self.tags.cost_tag_array()
        )

    def lbv2_target_group(self, *, identifier, health_path='/health?format=json') -> elbv2.TargetGroup:
        """ Creates LBv2 target group for the app.
            Like the portal, terminates HTTPS at the load balancer.
            Note that unlike the ECS services, these apps will NOT automatically associate with the target group!
            Navigate to the console to do so manually once ready.
        """
        name = f'TargetGroup{identifier}'
        logical_id = self.name.logical_id(name)
        return elbv2.TargetGroup(
            logical_id,
            HealthCheckIntervalSeconds=60,
            HealthCheckPath='/health?format=json',
            HealthCheckProtocol='HTTP',
            HealthCheckTimeoutSeconds=10,
            Matcher=elbv2.Matcher(HttpCode='200'),
            Name=name,
            Port=80,
            TargetType='ip',
            Protocol='HTTP',
            VpcId=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC),
            Tags=self.tags.cost_tag_array()
        )

    def application_load_balancer_listener(self, *, identifier, target_group: elbv2.TargetGroup) -> elbv2.Listener:
        """ Listener for the application load balancer, forwards traffic to the target group (JH). """
        logical_id = self.name.logical_id(f'{identifier}LBListener')
        return elbv2.Listener(
            logical_id,
            Port=80,
            Protocol='HTTP',
            LoadBalancerArn=Ref(self.application_load_balancer(identifier=identifier)),
            DefaultActions=[
                elbv2.Action(Type='forward', TargetGroupArn=Ref(target_group))
            ]
        )

    def application_load_balancer(self, *, identifier) -> elbv2.LoadBalancer:
        """ Application load balancer for JupyterHub. """
        lb_name = f'{identifier}LoadBalancer'
        logical_id = self.name.logical_id(lb_name)
        return elbv2.LoadBalancer(
            logical_id,
            IpAddressType='ipv4',
            Name=lb_name,  # was logical_id
            Scheme='internet-facing',
            SecurityGroups=[
                Ref(self.lb_security_group(identifier=identifier))
            ],
            Subnets=[self.NETWORK_EXPORTS.import_value(subnet_key) for subnet_key in C4NetworkExports.PUBLIC_SUBNETS],
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type='application',
        )
