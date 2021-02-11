from src.data_store import C4DataStore
from troposphere import Ref, Tags, Join, ImportValue, Output
from troposphere.elasticbeanstalk import (Application, ApplicationVersion, ConfigurationTemplate, Environment,
                                          ApplicationResourceLifecycleConfig, ApplicationVersionLifecycleConfig,
                                          OptionSettings, MaxAgeRule, MaxCountRule)


class C4Application(C4DataStore):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'make' method in C4Infra """

    BEANSTALK_SOLUTION_STACK = '64bit Amazon Linux 2018.03 v2.9.18 running Python 3.6'

    @classmethod
    def beanstalk_application(cls):
        """ Creates a Beanstalk Application, which has a related Configuration Template, where default configuration
            is defined, as `beanstalk_configuration_template`. Specific environments are spun off from this application
            e.g. production, dev, staging, etc. """
        name = cls.cf_id('Application')  # TODO more specific?
        return Application(
            name,
            ApplicationName=name,
            Description=name,
            DependsOn=[
                cls.https_security_group().title, cls.db_security_group().title, cls.virtual_private_cloud().title],
        )

    @classmethod
    def make_beanstalk_environment(cls, env):
        """ Creates Beanstalk Environments, which are associated with an overall Beanstalk Application. """
        env_name = 'cgap-{}'.format(env.lower())
        name = cls.cf_id('{}Environment'.format(env))
        return Environment(
            name,
            EnvironmentName=env_name,
            ApplicationName=Ref(cls.beanstalk_application()),
            # TODO CNAMEPrefix?
            # TODO Description?
            SolutionStackName='64bit Amazon Linux 2018.03 v2.9.18 running Python 3.6',
            Tags=Tags(*cls.cost_tag_array(name=name)),
            DependsOn=[
                cls.https_security_group().title, cls.db_security_group().title, cls.virtual_private_cloud().title],
        )

    @classmethod
    def dev_beanstalk_environment(cls):
        """ Defines a dev beanstalk environment, using pre-loaded ES inserts on instantiation """
        return cls.make_beanstalk_environment(env='Dev')

    @classmethod
    def beanstalk_configuration_option_settings(cls):
        """ Returns a list of ConfigurationOptionSetting for the base configuration template of a beanstalk
            application.
            Reference: https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/command-options-general.html """
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
                Value=Join(delimiter=',', values=[Ref(cls.https_security_group()), Ref(cls.db_security_group())]),
            ),
            # TODO SSHSourceRestriction from bastion host
            # TODO use scheduled actions: aws:autoscaling:scheduledaction. Ref:
            # https://docs.aws.amazon.com/elasticbeanstalk/latest/dg/environments-cfg-autoscaling-scheduledactions.html
            OptionSettings(
                Namespace='aws:ec2:instances',
                OptionName='InstanceTypes',
                Value='c5.large'
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='VPCId',
                Value=Ref(cls.virtual_private_cloud())  # check if this is equivalent to passing the vpc id
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='ELBSubnets',
                Value=Join(delimiter=',', values=[Ref(cls.public_subnet_a()), Ref(cls.public_subnet_b())])
            ),
            OptionSettings(
                Namespace='aws:ec2:vpc',
                OptionName='Subnets',
                Value=Join(delimiter=',', values=[Ref(cls.public_subnet_a()), Ref(cls.public_subnet_b())])
            ),
        ]

    @classmethod
    def beanstalk_configuration_template(cls):
        """ Returns the 'configuration template' for an application. Essentially the configuration defaults, which can
            be overridden on an environment-by-environment basis. """
        name = cls.cf_id('ConfigurationTemplate')  # more generic for multiple applications in the same infra?
        return ConfigurationTemplate(
            name,
            ApplicationName=Ref(cls.beanstalk_application()),
            Description='Base configuration template for beanstalk application',
            SolutionStackName=cls.BEANSTALK_SOLUTION_STACK,
            OptionSettings=cls.beanstalk_configuration_option_settings(),
            DependsOn=[
                cls.https_security_group().title, cls.db_security_group().title, cls.virtual_private_cloud().title],
        )

    @classmethod
    def beanstalk_application_version(cls):
        name = cls.cf_id('ApplicationVersion')
        return ApplicationVersion(
            name,
            # TODO
        )
