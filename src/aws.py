import boto3

from src.pricing_calculator import PricingCalculator

class AWSUtil(object):
    def __init__(self):
        self.MAIN_ACCOUNT_ID = "643366669028"

    @property
    def cloudwatch_client(self):
        """Return an open cloudwatch resource, authenticated with boto3+local creds"""
        return boto3.client('cloudwatch')

    @property
    def s3_resource(self):
        """Return an open s3 resource, authenticated with boto3+local creds"""
        return boto3.resource('s3')

    @property
    def s3_client(self):
        """Return an open s3 client, authenticated with boto3+local creds"""
        return boto3.client('s3')
