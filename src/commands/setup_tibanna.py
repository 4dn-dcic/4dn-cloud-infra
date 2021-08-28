import argparse
import boto3
import json

from botocore.client import ClientError
from dcicutils.misc_utils import ignorable, PRINT
from dcicutils.s3_utils import s3Utils
from ..base import ConfigManager
from ..parts.datastore import C4DatastoreExports


def bucket_head(*, bucket_name, s3=None):
    try:
        s3 = s3 or s3Utils().s3
        info = s3.head_bucket(Bucket=bucket_name)
        return info
    except ClientError:
        return None

def bucket_exists(*, bucket_name, s3=None):
    return bool(bucket_head(bucket_name=bucket_name, s3=s3))


def setup_tibanna():

    # Find out what tibanna output bucket is intended.

    intended_tibanna_output_bucket = C4DatastoreExports.get_tibanna_output_bucket()

    # Verify that a tibanna output bucket (possibly named ...-tibanna-logs or ...-tibanna-output) is set up at all.
    # This process will assure that the CGAP health page is reporting its name. That's where s3Utils gets the info.
    s3u = s3Utils()
    tibanna_output_bucket = s3u.tibanna_output_bucket
    if tibanna_output_bucket:
        PRINT(f"The S3 tibanna output bucket, {s3u.tibanna_output_bucket}, has been correctly set up.")
    else:
        PRINT(f"The S3 tibanna output bucket, {intended_tibanna_output_bucket}, is not available.")
        # ... hmm ... if s3u.fetch_health_page_json()

    if bucket_exists(bucket_name=tibanna_output_bucket, s3=s3u.s3):
        PRINT(f"The S3 tibanna output bucket, {tibanna_output_bucket}, exists on S3.")
    else:
        PRINT(f"The S3 tibanna output bucket, {tibanna_output_bucket}, does NOT exist on S3.")

    PRINT("NOTE: This only checked some things. No changes made. This is work in progress. More might still need to be done.")



def main(override_args=None):
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=None, type=str)
    args = parser.parse_args(args=override_args)
    ignorable(args)

    with ConfigManager.validate_and_source_configuration():
        setup_tibanna()


if __name__ == '__main__':
    main()
