# Force deletes the buckets named in the local file delete_pending_buckets.data.txt.
# Prompts for confirmation.
# See: https://github.com/4dn-dcic/4dn-cloud-infra/blob/master/docs/destroying_an_account.rst
# Created this 2022-06-14 when ran into problems deleting versioned S3 buckets using delete_pending_buckets;
# and doing it interactively in AWS console would require deleting each individual S3 bucket object separately/manually.

BUCKETS_LIST_FILE = "delete_pending_buckets.data.txt"

import boto3
import io
import os

def force_delete_s3_bucket(bucket_name):
    # Adapted from: https://stackoverflow.com/questions/29809105/how-do-i-delete-a-versioned-bucket-in-aws-s3-using-the-cli
    try:
        s3 = boto3.resource("s3")
        bucket = s3.Bucket(bucket_name)
        bucket.object_versions.delete()
        bucket.delete()
    except Exception as e:
        if "bucket does not exist" in str(e).lower():
            print(f"WARNING: Specified bucket ({bucket_name}) does not exist.")
        else:
            print(f"EXCEPTION: {str(e)}")

print(f"Force deleting S3 buckets listed in: {BUCKETS_LIST_FILE}")
print(f"AWS Access Key ID: {os.environ.get('AWS_ACCESS_KEY_ID')}")
print(f"AWS Secret Access Key: {os.environ.get('AWS_SECRET_ACCESS_KEY')[0] + '********'}")
with io.open(BUCKETS_LIST_FILE, "r") as buckets_list_fp:
    for bucket_name in buckets_list_fp.readlines():
        bucket_name = bucket_name.strip()
        response = input(f"Force delete S3 bucket: {bucket_name} ? [yes/no] ").strip().lower()
        if response == "yes":
            force_delete_s3_bucket(bucket_name)
        else:
            print(f"Skipping deletion of S3 bucket: {bucket_name}")
print("Done")
