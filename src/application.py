from src.data_store import C4DataStore


class C4Application(C4DataStore):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'make' method in C4Infra """

    @classmethod
    def beanstalk_application(cls):
        pass
