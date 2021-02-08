from src.data_store import C4DataStore
from troposphere import Ref
from troposphere.elasticbeanstalk import (Application, ApplicationVersion, ConfigurationTemplate, Environment,
                                          ApplicationResourceLifecycleConfig, ApplicationVersionLifecycleConfig,
                                          MaxAgeRule, MaxCountRule)


class C4Application(C4DataStore):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'make' method in C4Infra """

    @classmethod
    def beanstalk_application_version_lifecycle_config(cls):
        """ Add the lifecycle configuration for application versions. Currently based on max count, and not max age. """
        return ApplicationVersionLifecycleConfig(
            MaxAgeRule=MaxAgeRule(Enabled=False),
            MaxCountRule=MaxCountRule(
                DeleteSourceFromS3=False,  # TODO should this otherwise be garbage collected?
                Enabled=True,
                MaxCount=200),
        )

    @classmethod
    def beanstalk_application_resource_lifecycle_config(cls):
        """ The resource lifecycle config for a specific Beanstalk Application. """
        return ApplicationResourceLifecycleConfig(
            ServiceRole='arn:aws:iam::{0}:role/aws-elasticbeanstalk-service-role'.format(cls.ACCOUNT_NUMBER),
            VersionLifecycleConfig=Ref(cls.beanstalk_application_version_lifecycle_config())
        )

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
            ResourceLifecycleConfig=Ref(cls.beanstalk_application_resource_lifecycle_config())
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
            Tags=cls.cost_tag_array(name=name),
        )

    @classmethod
    def dev_beanstalk_environment(cls):
        """ Defines a dev beanstalk environment, using pre-loaded ES inserts on instantiation """
        return cls.make_beanstalk_environment(env='Dev')

    @classmethod
    def beanstalk_configuration_template(cls):
        """ Returns the 'configuration template' for an application. Essentially the configuration defaults, which can
            be overridden on an environment-by-environment basis. """
        name = cls.cf_id('ConfigurationTemplate')  # more generic for multiple applications in the same infra?
        return ConfigurationTemplate(
            name,
            ApplicationName=Ref(cls.beanstalk_application()),
        )

    @classmethod
    def beanstalk_application_version(cls):
        name = cls.cf_id('ApplicationVersion')
        return ApplicationVersion(
            name,
            # TODO
        )
