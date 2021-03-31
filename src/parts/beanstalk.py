import src.secrets as secrets
from src.part import C4Part
from src.exceptions import C4ApplicationException
from src.parts.network import C4NetworkExports
from troposphere import Ref, Tags, Join, Template, Parameter
from troposphere.elasticbeanstalk import (Application, ApplicationVersion, Environment,
                                          OptionSettings, SourceBundle)
from troposphere.elasticloadbalancingv2 import LoadBalancer, LoadBalancerAttributes, Listener, Action, RedirectConfig


class C4Beanstalk(C4Part):
    BEANSTALK_SOLUTION_STACK = '64bit Amazon Linux 2018.03 v2.9.18 running Python 3.6'
    APPLICATION_ENV_SECRET = 'dev/beanstalk/cgap-dev'  # name of secret in AWS Secret Manager; todo script initial add?
    NETWORK_EXPORTS = C4NetworkExports()

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # self.t.add_resource(self.beanstalk_shared_load_balancer())  TODO
        # self.t.add_resource(self.beanstalk_shared_load_balancer_listener())  TODO

        template.add_resource(self.beanstalk_application())
        template.add_resource(self.dev_beanstalk_environment())
        template.add_resource(self.beanstalk_application_version())

        return template

    def beanstalk_application_version(self,
                                      bucket='elasticbeanstalk-us-east-1-645819926742',
                                      key='my-trial-app-02/cgap-trial-account-b7.zip'):
        """ An existing application version source bundle. TODO: application version upload process """
        logical_id = self.name.logical_id('ApplicationVersion')
        return ApplicationVersion(
            logical_id,
            Description="Version 1.0",
            ApplicationName=Ref(self.beanstalk_application()),
            SourceBundle=SourceBundle(
                S3Bucket=bucket,
                S3Key=key,
            ),
        )

    def beanstalk_application(self):
        """ Creates a Beanstalk Application, Specific environments are spun off from this application
            e.g. production, dev, staging, etc. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-beanstalk.html
        """
        logical_id = self.name.logical_id('Application')  # TODO more specific?
        return Application(
            logical_id,
            ApplicationName=logical_id,
            Description=logical_id,
            # DependsOn=[
            #    self.beanstalk_security_group().title, self.db_security_group().title,
            #    self.virtual_private_cloud().title],
            # export
        )

    def beanstalk_shared_load_balancer(self, ip_address_type='ipv4', load_balancer_type='application'):
        """ Creates a shared load balancer for use by beanstalk environments. Refs:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticloadbalancingv2-loadbalancer.html
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-elasticloadbalancingv2-loadbalancer-loadbalancerattributes.html
        """
        logical_id = self.name.logical_id('SharedLoadBalancer')
        return LoadBalancer(
            logical_id,
            IpAddressType=ip_address_type,
            Name=logical_id,
            Scheme='internet-facing',
            SecurityGroups=[self.NETWORK_EXPORTS.import_value(
                C4NetworkExports.BEANSTALK_SECURITY_GROUP)],
            Subnets=[
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
                self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B),
            ],
            Tags=self.tags.cost_tag_array(name=logical_id),
            Type=load_balancer_type,  # 'application' is the default
            LoadBalancerAttributes=[
                LoadBalancerAttributes(
                    Key='idle_timeout.timeout_seconds',
                    Value='5'
                ),
                LoadBalancerAttributes(
                    Key='routing.http.desync_mitigation_mode',
                    Value='defensive'  # default
                ),
            ]
        )

    def beanstalk_shared_load_balancer_listener(self, port=80, protocol='HTTP'):
        """ Defines a listener on port 80 for a shared load balancer. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-resource-elasticloadbalancingv2-listener.html
            TODO unneeded? removed from infra config
        """
        logical_id = self.name.logical_id('SharedLoadBalancerListener')
        return Listener(
            logical_id,
            Port=port,
            Protocol=protocol,
            LoadBalancerArn=Ref(self.beanstalk_shared_load_balancer()),  # or, ARN directly?
            DefaultActions=[Action(Type='redirect', RedirectConfig=RedirectConfig())]
        )

    def make_beanstalk_environment(self, env):
        """ Creates Beanstalk Environments, which are associated with an overall Beanstalk Application. The specified
            env is passed through the options settings for parameterized change. Ref:
            https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-beanstalk-environment.html
        """
        env_name = 'fourfront-cgap{}'.format(env.lower())  # TODO change?
        logical_id = self.name.logical_id('{}Environment'.format(env))

        # TODO replace with docker specific env changes -- VersionLabel to demo application, SolutionStackName change
        if env.lower() == 'docker':
            raise C4ApplicationException('Docker environment implementation in progress')

        return Environment(
            logical_id,
            EnvironmentName=env_name,
            ApplicationName=Ref(self.beanstalk_application()),
            # TODO CNAMEPrefix?
            Description='CGAP {} env'.format(env),
            VersionLabel=Ref(self.beanstalk_application_version()),  # TODO configuration for deploying changes
            SolutionStackName=self.BEANSTALK_SOLUTION_STACK,
            Tags=Tags(*self.tags.cost_tag_array(name=logical_id)),
            OptionSettings=self.beanstalk_configuration_option_settings(),
            DependsOn=[
                # self.beanstalk_security_group().title, self.db_security_group().title,
                # self.virtual_private_cloud().title,
                self.beanstalk_application()],
        )

    def dev_beanstalk_environment(self):
        """ Defines a dev beanstalk environment, using pre-loaded ES inserts on instantiation """
        return self.make_beanstalk_environment(env='Dev')

    def docker_beanstalk_environment(self):
        """ Sketch of how to support a docker environment on this application, using the demo docker application. """
        return self.make_beanstalk_environment(env='Docker')

    def beanstalk_configuration_option_settings(self):
        """ Returns a list of OptionSettings for the base configuration of a beanstalk environment. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html
        """
        # TODO SSHSourceRestriction from bastion host
        # TODO use scheduled actions: aws:autoscaling:scheduledaction. Ref:
        # https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/environments-cfg-autoscaling-scheduledactions.html

        # Choose platform-specific options based on env. Defaults to Python Platform. TODO: other platforms?
        platform = self.python_platform_options()
        return (
                self.launchconfiguration_options() +
                self.instances_options() +
                self.vpc_options() +
                self.environment_options() +
                self.application_environment_options() +
                platform +
                self.asg_options() +
                self.loadbalancer_options() +
                self.rolling_options() +
                self.health_options()
                # cls.shared_alb_listener_options(env) +
                # cls.shared_alb_listener_default_rule_options(env)  TODO unneeded?
        )

    # Beanstalk Options #

    def launchconfiguration_options(self):
        """ Returns list of OptionsSettings for beanstalk launch configuration. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-autoscalinglaunchconfiguration
        """
        return [
            OptionSettings(
                Namespace='aws:autoscaling:launchconfiguration',
                OptionName='EC2KeyName',
                Value='trial-ssh-key-01'  # pem key for EC2 instance access; TODO configurable
            ),
            OptionSettings(
                Namespace='aws:autoscaling:launchconfiguration',
                OptionName='IamInstanceProfile',
                Value='aws-elasticbeanstalk-ec2-role'
            ),
            OptionSettings(
                Namespace='aws:autoscaling:launchconfiguration',
                OptionName='MonitoringInterval',
                Value='5 minute'  # default is 5 min; TODO should this be 1 min?
            ),
            OptionSettings(
                Namespace='aws:autoscaling:launchconfiguration',
                OptionName='SecurityGroups',  # TODO correct security groups
                Value=Join(delimiter=',', values=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.BEANSTALK_SECURITY_GROUP),
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.DB_SECURITY_GROUP)]),
            ),
        ]

    @staticmethod
    def instances_options():
        """ Returns list of OptionsSettings for beanstalk instances. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-ec2instances
        """
        return [
            OptionSettings(
                Namespace='aws:ec2:instances',
                OptionName='InstanceTypes',
                Value='c5.large'
            ),
        ]

    def vpc_options(self):
        """ Returns list of OptionSettings for beanstalk VPC. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-ec2vpc
        """
        return [
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='VPCId',
                Value=self.NETWORK_EXPORTS.import_value(C4NetworkExports.VPC)
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='ELBSubnets',
                Value=Join(delimiter=',', values=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_A),
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PUBLIC_SUBNET_B)])
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='Subnets',
                Value=Join(delimiter=',', values=[
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_A),
                    self.NETWORK_EXPORTS.import_value(C4NetworkExports.PRIVATE_SUBNET_B)])
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='ELBScheme',
                Value='public'  # default
            ),
        ]

    def beanstalk_env_secret_retrieval(self, key):
        """ Retrieve key from beanstalk env secret stored in AWS Secret Manager, for use in a Cloud Formation template.
            TODO manage this secret name via Cloud Formation?
        """
        return '{{resolve:secretsmanager:{}:SecretString:{}}}'.format(self.APPLICATION_ENV_SECRET, key)

    @staticmethod
    def application_environment_options():
        """ Returns list of OptionSettings for beanstalk application environment. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elasticbeanstalkapplicationenvironment
        """
        # Create OptionSettings for each environment variable, secure retrieval from Secrets Manager TODO
        # >>> keys = ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SECRET_KEY', 'Auth0Client', 'Auth0Secret',
        # 'ENCODED_BS_ENV', 'ENCODED_DATA_SET', 'ENCODED_ES_SERVER', 'ENCODED_SECRET', 'ENCODED_VERSION',
        #       'ENV_NAME', 'LANG', 'LC_ALL', 'RDS_PASSWORD', 'RDS_DB_NAME', 'RDS_HOSTNAME', 'RDS_PORT', 'RDS_USERNAME',
        #        'S3_ENCRYPT_KEY', 'SENTRY_DSN', 'reCaptchaSecret']
        # >>> for i in keys:
        #       print('''OptionSettings(\n
        #       Namespace='aws:elasticbeanstalk:application:environment',\n
        #       OptionName='{0}',\n    Value=secrets.{0}\n),'''.format(i))
        return [
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='AWS_ACCESS_KEY_ID',
                Value=secrets.AWS_ACCESS_KEY_ID
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='AWS_SECRET_ACCESS_KEY',
                Value=secrets.AWS_SECRET_ACCESS_KEY
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='AWS_SECRET_KEY',
                Value=secrets.AWS_SECRET_KEY
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='Auth0Client',
                Value=secrets.Auth0Client
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='Auth0Secret',
                Value=secrets.Auth0Secret
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENCODED_BS_ENV',
                Value=secrets.ENCODED_BS_ENV
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENCODED_DATA_SET',
                Value=secrets.ENCODED_DATA_SET
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENCODED_ES_SERVER',
                Value=secrets.ENCODED_ES_SERVER
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENCODED_SECRET',
                Value=secrets.ENCODED_SECRET
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENCODED_VERSION',
                Value=secrets.ENCODED_VERSION
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='ENV_NAME',
                Value=secrets.ENV_NAME
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='LANG',
                Value=secrets.LANG
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='LC_ALL',
                Value=secrets.LC_ALL
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='RDS_PASSWORD',
                Value=secrets.RDS_PASSWORD
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='RDS_DB_NAME',
                Value=secrets.RDS_DB_NAME
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='RDS_HOSTNAME',
                Value=secrets.RDS_HOSTNAME
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='RDS_PORT',
                Value=secrets.RDS_PORT
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='RDS_USERNAME',
                Value=secrets.RDS_USERNAME
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='S3_ENCRYPT_KEY',
                Value=secrets.S3_ENCRYPT_KEY
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='SENTRY_DSN',
                Value=secrets.SENTRY_DSN
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application:environment',
                OptionName='reCaptchaSecret',
                Value=secrets.reCaptchaSecret
            ),
        ]

    @staticmethod
    def environment_options():
        """ Returns list of OptionSettings for beanstalk environment. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elasticbeanstalkenvironment
        """
        return [
            OptionSettings(
                Namespace='aws:elasticbeanstalk:environment',
                OptionName='EnvironmentType',
                Value='LoadBalanced'  # default
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:environment',
                OptionName='ServiceRole',
                Value='arn:aws:iam::645819926742:role/aws-elasticbeanstalk-service-role'
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:environment',
                OptionName='LoadBalancerType',
                Value='application'
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:environment',
                OptionName='LoadBalancerIsShared',
                Value='false'  # default TODO set to true; requires configuration in aws:elbv2:loadbalancer namespace
            ),
        ]

    @staticmethod
    def python_platform_options():
        """ Returns list of OptionSettings for beanstalk python platform. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-specific.html#command-options-python
        """
        return [
            OptionSettings(
                Namespace='aws:elasticbeanstalk:container:python',
                OptionName='WSGIPath',
                Value='parts/production/wsgi'
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:container:python',
                OptionName='NumProcesses',
                Value='5'
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:container:python',
                OptionName='NumThreads',
                Value='4'
            ),
        ]

    @staticmethod
    def asg_options():
        """ Returns list of OptionSettings for beanstalk auto-scaling group. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-autoscalingasg
        """
        return [
            OptionSettings(
                Namespace='aws:autoscaling:asg',
                OptionName='MaxSize',
                Value='1'
            ),
        ]

    def loadbalancer_options(self):
        """ Returns list of OptionsSettings for beanstalk loadbalancer. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elbv2
        """
        return [
            OptionSettings(
                Namespace='aws:elbv2:loadbalancer',
                OptionName='SecurityGroups',
                Value=self.NETWORK_EXPORTS.import_value(C4NetworkExports.BEANSTALK_SECURITY_GROUP)
            ),
            # OptionSettings(
            #   Namespace='aws:elbv2:loadbalancer',
            #   OptionName='SharedLoadBalancer',
            #   Value=Ref(cls.beanstalk_shared_load_balancer())
            # ),  TODO Shared Load Balancer
        ]

    @staticmethod
    def rolling_options():
        """ Returns list of OptionsSettings for beanstalk rolling updates. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-autoscalingupdatepolicyrollingupdate
        """
        return [
            OptionSettings(
                Namespace='aws:autoscaling:updatepolicy:rollingupdate',
                OptionName='Timeout',
                Value='PT10M'  # 10 minutes
            ),
            OptionSettings(
                Namespace='aws:autoscaling:updatepolicy:rollingupdate',
                OptionName='RollingUpdateType',
                Value='Immutable'
            ),
        ]

    @staticmethod
    def shared_alb_listener_options():
        """ Returns list of OptionSettings for a shared ALB listening on port 80. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elbv2-listener
        """
        return [
            OptionSettings(
                Namespace='aws:elbv2:listener:80',
                OptionName='Rules',
                Value='defaultshared'
                # rules defined in `shared_alb_listener_default_rule_options` with namespace:
                # aws:elbv2:listenerrule:defaultshared
            )
        ]

    @staticmethod
    def shared_alb_listener_default_rule_options():
        """ Returns list of OptionSettings for the default rules of a shared ALB listener. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elbv2-listenerrule
            See also `shared_alb_listener_options`.
        """
        return [
            OptionSettings(
                Namespace='aws:elbv2:listenerrule:defaultshared',
                OptionName='PathPatterns',
                Value='*'  # TODO '/*'?
            ),
            # By default, routes to 'default' process.
        ]

    @staticmethod
    def health_options():
        """ Returns list of OptionSettings for the beanstalk health reporting options. Ref:
            https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html#command-options-general-elasticbeanstalkhealthreporting
        """
        return [
            OptionSettings(
                Namespace='aws:elasticbeanstalk:healthreporting:system',
                OptionName='SystemType',
                Value='enhanced'
            ),
            OptionSettings(
                Namespace='aws:elasticbeanstalk:application',
                OptionName='Application Healthcheck URL',
                Value='/health?format=json'
            )
        ]
