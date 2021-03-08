from src.data_store import C4DataStore

from troposphere import (
    Parameter,
    Join,
    Ref,
    elasticloadbalancing as elb,
)
from troposphere.ecs import (
    Cluster,
)
from troposphere.ec2 import (
    SecurityGroup,
    SecurityGroupRule,
)


class C4ECSApplication(C4DataStore):
    """ Configures the ECS Cluster Application for CGAP
        This class contains everything necessary for running CGAP on ECS, including:
            * The Cluster itself (done)
            * TODO The Load Balancer that forwards traffic to the Cluster (partway done)
            * TODO Container instance
            * TODO Autoscaling Group
            * TODO ECS Service
            * TODO ECS Task
    """

    @classmethod
    def ecs_cluster(cls):
        return Cluster(
            'CGAPDockerCluster'
        )

    @classmethod
    def ecs_lb_certificate(cls):
        return Parameter(
            "CertId",
            Description='This is the SSL Cert to attach to the LB',
            Type='String'
        )

    @classmethod
    def ecs_web_worker_port(cls):
        return Parameter(
            'WebWorkerPort',
            Description="Web worker container exposed port",
            Type="Number",
            Default="8000",  # should work for us
        )

    @classmethod
    def ecs_lb_security_group(cls):
        return SecurityGroup(
            "ECSLBSSLSecurityGroup",
            GroupDescription="Web load balancer security group.",
            VpcId=cls.cf_id('VPC'),
            SecurityGroupIngress=[
                SecurityGroupRule(
                    IpProtocol="tcp",
                    FromPort="443",
                    ToPort="443",
                    CidrIp='0.0.0.0/0',
                ),
            ],
        )

    @classmethod
    def ecs_load_balancer(cls):
        return elb.LoadBalancer(
            'ECSLoadBalancer',
            Subnets=[
                # TODO How to specify the 2 public subnets?
            ],
            SecurityGroups=[Ref(cls.ecs_lb_security_group())],
            Listeners=[elb.Listener(
                LoadBalancerPort=443,
                InstanceProtocol='HTTP',
                InstancePort=Ref(cls.ecs_web_worker_port()),
                Protocol='HTTPS',
                SSLCertificateId=Ref(cls.ecs_lb_certificate()),
            )],
            HealthCheck=elb.HealthCheck(
                Target=Join("", ["HTTP:", Ref(cls.ecs_web_worker_port()), "/health"]),
                HealthyThreshold="2",
                UnhealthyThreshold="2",
                Interval="120",
                Timeout="10",
            ),
        )

    @classmethod
    def ecs_container_instance_type(cls):
        return Parameter(
            'ContainerInstanceType',
            Description='The container instance type',
            Type="String",
            Default="c5.large",
            AllowedValues=['c5.large']  # configure more later
        )
