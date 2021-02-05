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
        return ApplicationVersionLifecycleConfig(
            MaxAgeRule=MaxAgeRule(),
            MaxCountRule=MaxCountRule(),
        )

    @classmethod
    def beanstalk_application_resource_lifecycle_config(cls):
        return ApplicationResourceLifecycleConfig(
            ServiceRole='arn:aws:iam::645819926742:role/aws-elasticbeanstalk-service-role',
            # TODO - ^ account number configurable?
            VersionLifecycleConfig=Ref(cls.beanstalk_application_version_lifecycle_config())
        )

    @classmethod
    def beanstalk_application(cls):
        name = cls.cf_id('Application')
        return Application(
            name,
            ApplicationName=name,
            Description=name,
            ResourceLifecycleConfig=Ref(cls.beanstalk_application_resource_lifecycle_config())
        )

    @classmethod
    def beanstalk_environment(cls):
        name = cls.cf_id('Environment')
        return Environment(
            name,
            # TODO
        )

    @classmethod
    def beanstalk_configuration_template(cls):
        name = cls.cf_id('ConfigurationTemplate')
        return ConfigurationTemplate(
            name,
            # TODO
        )

    @classmethod
    def beanstalk_application_version(cls):
        name = cls.cf_id('ApplicationVersion')
        return ApplicationVersion(
            name,
            # TODO
        )
