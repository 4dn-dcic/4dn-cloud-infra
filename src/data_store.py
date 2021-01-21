from src.network import C4Network
from troposphere import Join, Ref
from troposphere.rds import DBInstance
from troposphere.secretsmanager import Secret, GenerateSecretString, SecretTargetAttachment


class C4DataStore(C4Network):
    """ Class methods below construct the troposphere representations of AWS resources, without building the template
        1) Add resource as class method below
        2) Add to template in a 'mk' method in C4Infra """

    RDS_SECRET_STRING = 'RDSSecret'  # Generate Secret ID with `cls.cf_id(RDS_SECRET_STRING)`

    @classmethod
    def rds_secret(cls):
        """ Returns the RDS secret, as generated and stored by AWS Secrets Manager """
        return Secret(
            cls.cf_id(cls.RDS_SECRET_STRING),
            Name=cls.cf_id(cls.RDS_SECRET_STRING),
            Description='This is the RDS instance master password',
            GenerateSecretString=GenerateSecretString(
                SecretStringTemplate='{"username":"admin"}',
                GenerateStringKey='password',
                PasswordLength=30,
            ),
            Tags=cls.cost_tag_array(),
        )

    @classmethod
    def rds_instance(cls):
        """ Returns the single RDS instance for the infrastructure stack """
        rds_id = cls.cf_id('RDS')
        return DBInstance(
            rds_id,
            AllocatedStorage=20,
            DBInstanceClass='db.t3.medium',
            Engine='postgres',
            DBInstanceIdentifier=cls.cf_id('RDS'),
            DBName='postgresql',
            CopyTagsToSnapshot=True,
            AvailabilityZone='us-east-1a',
            VPCSecurityGroups=[Ref(cls.db_security_group())],
            MasterUsername=Join('', [
                '{{resolve:secretsmanager:',
                {'Ref': cls.cf_id(cls.RDS_SECRET_STRING)},
                ':SecretString:username}}'
            ]),
            MasterUserPassword=Join('', [
                '{{resolve:secretsmanager:',
                {'Ref': cls.cf_id(cls.RDS_SECRET_STRING)},
                ':SecretString:password}}'
            ]),
            Tags=cls.cost_tag_array(name=rds_id),
        )

    @classmethod
    def rds_secret_attachment(cls):
        """ Attaches the rds_secret to the rds_instance. """
        return SecretTargetAttachment(
            cls.cf_id('SecretRDSInstanceAttachment'),
            TargetType='AWS::RDS::DBInstance',
            SecretId=Ref(cls.rds_secret()),
            TargetId=Ref(cls.rds_instance()),
        )

    @classmethod
    def elasticsearch_instance(cls):
        pass

    @classmethod
    def sqs_instance(cls):
        pass
