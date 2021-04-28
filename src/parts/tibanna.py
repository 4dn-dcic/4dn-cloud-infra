"""
cloud-infra tibanna --init
cloud-infra tibanna --verify
"""
import logging
from troposphere import Template
from troposphere.s3 import Bucket, Private
from src.part import C4Part

logger = logging.getLogger(__name__)


class C4Tibanna(C4Part):
    TRIAL_GROUP = 'tibanna_unicorn_trial_tibanna_unicorn_02'  # trial tibanna group w/ private buckets configured
    TRIAL_ID = '52303648'  # trial tibanna ID for (globally namespaced) private buckets; TODO configurable
    # tibanna groups:
    # tibanna_unicorn_trial_tibanna_unicorn_01 - uses public buckets on the prod account for testing
    # tibanna_unicorn_trial_tibanna_unicorn_02 - uses private buckets on the trial account, configured here

    def initial_deploy(self, usergroup=TRIAL_GROUP, dry_run=True):
        """ Runs the initial deploy of tibanna for a usergroup"""
        cmd = 'tibanna deploy_unicorn --usergroup={usergroup}'.format(usergroup=usergroup)
        if dry_run:
            logger.warning('initial_deploy would run: {cmd}'.format(cmd=cmd))
        else:
            self.account.run_command(cmd)

    def list_users(self):
        """ Lists users and tibanna usergroups for this account """
        cmd = 'tibanna users'
        self.account.run_command(cmd)

    def build_template(self, template: Template) -> Template:
        """ Adds tibanna-required resources to the troposphere template """
        template.add_resource(self.private_tibanna_data_bucket())
        template.add_resource(self.private_tibanna_log_bucket())
        return template

    def private_tibanna_data_bucket(self):
        """ Builds the private tibanna data bucket. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-s3-bucket.html
        """
        bucket_id = 'DataId{tibanna_id}Bucket'.format(tibanna_id=self.TRIAL_ID)
        return self.build_tibanna_bucket(bucket_id=bucket_id)

    def private_tibanna_log_bucket(self):
        """ Builds the private tibanna log bucket. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-s3-bucket.html
        """
        bucket_id = 'LogId{tibanna_id}Bucket'.format(tibanna_id=self.TRIAL_ID)
        return self.build_tibanna_bucket(bucket_id=bucket_id)

    def build_tibanna_bucket(self, bucket_id, access_control=Private) -> Bucket:
        """ Creates a Tibanna S3 bucket with the given bucket id and access control permissions. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-s3-bucket.html
        """
        logical_id = self.name.logical_id(bucket_id)
        bucket_name = self.name.bucket_name_from_logical_id(logical_id=logical_id)
        return Bucket(
            logical_id,
            BucketName=bucket_name,
            AccessControl=access_control,
            Tags=self.tags.cost_tag_obj(),
        )
