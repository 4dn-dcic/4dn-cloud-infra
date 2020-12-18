import boto3
import csv
import logging
import sys

import concurrent.futures
from botocore.exceptions import ClientError
from datetime import datetime, timedelta

from src.pricing_calculator import PricingCalculator


class AWSUtil:
    """ Define the constants used by util methods."""
    MAIN_ACCOUNT_ID = "643366669028"
    BUCKET_SUMMARY_FILENAME = 'out/{}_run_results.tsv'.format(datetime.now().date())
    BUCKET_SUMMARY_HEADER = [
        'name', 'project tag', 'env tag', 'owner tag', 'size in bytes', 'readable size', 'estimated monthly cost']

    VERSION_SUMMARY_FILENAME_FORMAT = 'out/latest_run_for_versioned_bucket_{}.tsv'
    VERSION_SUMMARY_HEADER = [
        'object name',
        'latest version size',
        'number of past versions',
        'total size of all versions',
        'is it deleted',
        'last modified'
    ]
    # https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuoverview.html#mpu-stop-incomplete-mpu-lifecycle-config
    # boto3 => S3Control.Client.put_bucket_lifecycle_configuration
    INCOMPLETE_UPLOAD_ID = 'incomplete-upload-rule'
    INCOMPLETE_UPLOAD_RULE = {
        'ID': INCOMPLETE_UPLOAD_ID,
        'Status': 'Enabled',
        'Filter': {
            'Prefix': ''
        },
        'AbortIncompleteMultipartUpload': {
            'DaysAfterInitiation': 14
        }
    }
    # The string to be printed in a tsv when describing the non-existent size of a deleted file
    SIZE_STRING_FOR_DELETED_FILE = 'N/A (deleted)'

    # The string to be printed in a tsv when describing the value of a tag that has not been assigned for a resource
    TAG_STRING_FOR_UNASSIGNED_TAG = '-'

    @property
    def cloudwatch_client(self):
        """ Return an open cloudwatch resource, authenticated with boto3+local creds"""
        return boto3.client('cloudwatch')

    @property
    def s3_resource(self):
        """ Return an open s3 resource, authenticated with boto3+local creds"""
        return boto3.resource('s3')

    @property
    def s3_client(self):
        """ Return an open s3 client, authenticated with boto3+local creds"""
        return boto3.client('s3')

    def get_tag_optional(self, tags, t):
        """ Returns the tag t in the dictionary tag_set with an default value if missing"""
        return tags.get(t, self.TAG_STRING_FOR_UNASSIGNED_TAG)

    def generate_s3_bucket_summary_tsv(self, dry_run=True, upload=False):
        """ Generates a summary tsv of the S3 Buckets used by CGAP/4DN."""

        # Write the tsv to stdout if it's a dry run (to debug), otherwise write to an output file
        with open(self.BUCKET_SUMMARY_FILENAME if not dry_run else sys.stdout, 'w', newline='') as tsvfile:
            writer = csv.writer(tsvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(self.BUCKET_SUMMARY_HEADER)

            # Get all buckets + their tags
            bucket_tags = self.get_bucket_tags()

            # Construct and execute a CloudWatch query, for all bucket sizes in bytes
            bytes_query = self.cloudwatch_bucket_bytes_query(bucket_tags.keys())
            response = self.request_cloudwatch_bucket_metric_data(bytes_query)

            # Associate the response results with a bucket tags to build the column
            for idx, result in enumerate(response['MetricDataResults']):
                name = result['Label']
                tags = bucket_tags[name]
                assert len(result['Timestamps']) == len(result['Values'])
                assert len(result['Values']) == 1 or len(result['Values']) == 0
                project_tag = self.get_tag_optional(tags, 'project')
                env_tag = self.get_tag_optional(tags, 'env')
                owner_tag = self.get_tag_optional(tags, 'owner')
                if len(result['Values']) == 0:  # Case of an empty bucket (or a broken time range in the query)
                    size_bytes = float(0)
                    size_readable = '0'
                    size_price = '$0.00'
                else:
                    size_bytes = float(result['Values'][0])
                    size_readable = PricingCalculator.bytes_to_readable(size_bytes)
                    size_price = PricingCalculator.bytes_to_price(size_bytes)
                writer.writerow([name, project_tag, env_tag, owner_tag, size_bytes, size_readable, size_price])

    @staticmethod
    def request_object_versions(client, bucket, follow_up_request=False,
                                next_key_marker=None, next_version_id_marker=None):
        """ Given an s3 client and a bucket, makes a single request for object versions. If this is a follow up request,
            passes the next markers in the request. Returns the response from the client, including the markers needed
            for subsequent requests."""
        assert follow_up_request is True and next_key_marker and next_version_id_marker \
            or follow_up_request is False and next_key_marker is None and next_version_id_marker is None
        if follow_up_request:
            response = client.list_object_versions(
                Bucket=bucket,
                KeyMarker=next_key_marker,
                VersionIdMarker=next_version_id_marker)
            return response
        else:
            response = client.list_object_versions(Bucket=bucket)
            return response

    def generate_versioned_files_summary_tsvs(self):
        """ Generates summary spreadsheets for 1) deleted objects and 2) multi-versioned objects
            in S3 buckets with versioning enabled."""
        # TODO query for this list instead
        versioned_buckets = [
            'elasticbeanstalk-fourfront-staging-blobs',
            'elasticbeanstalk-fourfront-staging-files',
            'elasticbeanstalk-fourfront-staging-system',
            'elasticbeanstalk-fourfront-staging-wfoutput',
            'elasticbeanstalk-fourfront-webdev-essentials-pack',
            'elasticbeanstalk-fourfront-webdev-files',
            'elasticbeanstalk-fourfront-webprod-blobs',
            'elasticbeanstalk-fourfront-webprod-files',
            'elasticbeanstalk-fourfront-webprod-system',
            'elasticbeanstalk-fourfront-webprod-wfoutput',
            'elasticbeanstalk-us-east-1-643366669028',
            'foursight-envs',
            'jupyterhub-fourfront-notebooks',
            'jupyterhub-fourfront-templates'
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=4) as executor:
            executor.map(self.generate_versioned_files_summary_tsv_for_bucket, versioned_buckets, chunksize=4)
        print('Generated all tsvs.')

    def aggregate_version_data(self, total_response):
        """ Takes a list of response dictionaries as input, as described here:
            boto3.amazonaws.com/v1/documentation/api/latest/reference/services/s3.html#S3.Client.list_object_versions

            Joins the truncated responses together, filters for multi-versioned and deleted files,
            and returns aggregate information on each multi-versioned or deleted file. Ignores files with only
            one version.
            """
        data = {}
        for response in total_response:
            if 'Versions' in response:
                for v in response['Versions']:
                    if v['IsLatest']:
                        latest = True
                    else:
                        latest = False
                    key = v.get('Key', 'no-key')
                    if key in data:
                        if latest:
                            data[key]['versions'].append(v)
                            data[key]['latest'] = v['ETag']
                        else:
                            data[key]['versions'].append(v)
                    else:
                        data[key] = {'versions': [v], 'delete_marker': None}
            if 'DeleteMarkers' in response:
                for d in response['DeleteMarkers']:
                    key = d.get('Key', 'no-key')
                    if key in data:
                        if data[key]['delete_marker'] is None:
                            data[key]['delete_marker'] = [d]
                        else:
                            data[key]['delete_marker'].append(d)
                    else:
                        data[key] = {'versions': [], 'delete_marker': [d]}
        actionable_data = {}
        unactionable_data = {}
        for k in data.keys():
            versions = data[k]['versions']
            delete_marker = data[k]['delete_marker']
            if delete_marker:
                actionable_data[k] = data[k]
            elif len(versions) > 1:
                actionable_data[k] = data[k]
            else:
                unactionable_data[k] = data[k]
        assert len(unactionable_data) == sum([len(unactionable_data[i]['versions']) for i in unactionable_data.keys()])

        # TODO messy, needs refactoring
        for k in actionable_data.keys():
            v = actionable_data[k]
            total_size = sum([int(i['Size']) for i in v['versions']])
            if v['delete_marker']:
                latest = v['delete_marker'][0]['LastModified']
                size = self.SIZE_STRING_FOR_DELETED_FILE
            else:
                latest = [i for i in v['versions'] if i['IsLatest'] is True][0]['LastModified']
                size = [i for i in v['versions'] if i['IsLatest'] is True][0]['Size']
                # TODO remove latest from actionable object gen
            good_data = {
                'name': k,
                'size': size,
                'version_num': len(v['versions']),
                'total_size': total_size,
                'deleted': True if v['delete_marker'] else False,
                'last_mod': latest
            }
            actionable_data[k] = good_data
        return actionable_data

    def generate_versioned_files_summary_tsv_for_bucket(self, bucket='elasticbeanstalk-fourfront-webprod-wfoutput',
                                                        complete_run=True):
        """ Takes a versioned bucket name, and writes a tsv for all versions of the bucket
            complete_run will run the full bucket, otherwise it'll only run for the first ~1000 versions.

            TODO perhaps make complete_run configurable elsewhere
        """

        logging.basicConfig(level=logging.INFO, filename='log/{}.log'.format(bucket), filemode='a+',
                            format='%(asctime)-15s %(levelname)-8s %(message)s')
        logging.info('Starting run for {}'.format(bucket))

        client = self.s3_client
        filename = self.VERSION_SUMMARY_FILENAME_FORMAT.format(bucket)
        # Excel cares about the filename for import, GSheets doesn't care

        logging.info('Generating csv for {}'.format(bucket))
        logging.info('Retrieving data from AWS...')
        first_response = self.request_object_versions(client, bucket)
        total_response = [first_response]

        if complete_run:
            logging.info('Retrieving data chunks in a loop..')
            while total_response[-1]['IsTruncated']:
                next_key_marker = total_response[-1]['NextKeyMarker']
                next_version_id_marker = total_response[-1]['NextVersionIdMarker']
                next_response = self.request_object_versions(
                    client, bucket, True,
                    next_key_marker=next_key_marker,
                    next_version_id_marker=next_version_id_marker)
                total_response.append(next_response)

        logging.info('Data retrieved from AWS. Aggregating...')
        actionable_data = self.aggregate_version_data(total_response)
        logging.info('Generating spreadsheet...')
        with open(filename, 'w', newline='') as tsvfile:
            writer = csv.writer(tsvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(self.VERSION_SUMMARY_HEADER)
            for i in actionable_data:
                writer.writerow([
                    actionable_data[i]['name'],
                    actionable_data[i]['size'],
                    actionable_data[i]['version_num'],
                    actionable_data[i]['total_size'],
                    actionable_data[i]['deleted'],
                    actionable_data[i]['last_mod']
                ])

        logging.info('wrote {}'.format(filename))

    def update_tags_from_input_csv(self, dry_run=True):
        """ When dry_true = False, this replaces all tags for all S3 Buckets with
        three defined in the spreadsheet: env, project, and owner. All other tags will be removed."""
        filename = 'input_tags_needing_updating.csv'
        rows = []

        # Validate data, load relevant columns into a list of dicts
        with open(filename, newline='') as csvfile:
            reader = csv.reader(csvfile, delimiter=',', quotechar='|')

            for idx, row in enumerate(reader):
                if row[0] == 'Identifier':
                    assert row[:7] == [
                        'Identifier', 'Service', 'Type', 'Region', 'Tag: env', 'Tag: project', 'Tag: owner']
                elif row[0] != '':  # ignore empty rows w/ no identifier
                    assert row[1] == 'S3', 'row {} has {} as service'.format(idx, row[1])
                    assert row[2] == 'Bucket', 'row {} has {} as type'.format(idx, row[2])
                    rows.append({
                        'bucket_name': row[0],
                        'region': row[3],
                        'env': row[4],
                        'project': row[5],
                        'owner': row[6]
                    })
                else:
                    pass  # empty row

        # Open a BucketTagging resource for each bucket
        # construct tagging objects, return them if dry_run, else execute
        resource = self.s3_resource
        for idx, bucket in enumerate(rows):
            bucket_tagging_resource = resource.BucketTagging(bucket['bucket_name'])
            bucket['bucket_tagging_resource'] = bucket_tagging_resource
            # Fix case where owner = '-' which should be None
            if bucket.get('owner', None) == '-':
                bucket['owner'] = None
            # Build request object
            tag_set = []
            for tag in ('env', 'project', 'owner'):
                if bucket[tag]:
                    tag_set.append({'Key': tag, 'Value': bucket[tag]})
            bucket['tagging'] = {
                'TagSet': tag_set
            }

        # Return the to_update obj if dry_run, run otherwise
        if dry_run:
            return rows  # verify [i['tagging'] for i in rows ]

        else:
            for i in rows:
                # TODO logging output
                print('Updating tags for bucket {} with tagging object {}'.format(i['bucket_name'], i['tagging']))
                i['bucket_tagging_resource'].put(Tagging=i['tagging'])  # Returns None

    @staticmethod
    def flatten_tag_set(tag_set):
        """ Flattens the more verbose tag set result from AWS into a simpler dictionary, removing the 'Key' and 'Value'
            keys in favor of making the 'Key' value the key and the 'Value' key the value"""
        return {ts['Key']: ts['Value'] for ts in tag_set}

    def get_bucket_names(self):
        """ Returns list of s3 bucket names as queried from AWS"""
        return [r.name for r in self.s3_resource.buckets.all()]

    def get_bucket_tags(self):
        """ Returns a dictionary of bucket names and flattened tag sets, as queried from AWS"""
        resource = self.s3_resource
        bucket_tags = {r.name: r.Tagging().tag_set for r in resource.buckets.all()}
        return {k: self.flatten_tag_set(v) for k, v in bucket_tags.items()}

    def get_bucket_lifecycle(self, bucket):
        """ Get the lifecycle configurations for the bucket. See:
            https://docs.aws.amazon.com/AmazonS3/latest/dev/object-lifecycle-mgmt.html"""
        resource = self.s3_resource
        return resource.BucketLifecycleConfiguration(bucket)

    def append_upload_cancellation_to_buckets(self, test=True, dry_run=True):
        """ Fetches the lifecycle configuration for S3 buckets, appends the multi-upload cancellation policy, and
        uploads to S3. If test is True, only does this for 'gem-upload-bucket'.
        TODO: logging decorator
        TODO: this should be ported to CloudFormation/troposphere"""
        logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)-8s %(message)s')
        if test:
            buckets = ['gem-upload-bucket']
            logging.info('Uploading multi-upload cancellation to "gem-upload-bucket" only..')
        else:
            buckets = self.get_bucket_names()
            logging.info('Uploading multi-upload cancellation to all buckets..')
        for b in buckets:
            lifecycle_resource = self.get_bucket_lifecycle(b)
            try:
                rules = lifecycle_resource.rules
            except ClientError as ex:
                if 'NoSuchLifecycleConfiguration' in str(ex):
                    rules = []
                else:
                    raise ex
            # Only run the update if the multi-upload rule is not currently present
            # TODO optionally enable updates to this policy
            if self.INCOMPLETE_UPLOAD_ID not in [r['ID'] for r in rules]:
                logging.info('Adding incomplete upload rule for bucket {}...'.format(b))
                rules.append(self.INCOMPLETE_UPLOAD_RULE)
                if dry_run:
                    logging.info('dry run: would run lifecycle resource put otherwise')
                    logging.info('rules: {}'.format(rules))
                else:
                    lifecycle_resource.put(
                        LifecycleConfiguration={
                            'Rules': rules
                        }
                    )
            else:
                logging.info('Incomplete upload rule already present for bucket {}. Skipping...'.format(b))
                logging.info('{}'.format(rules))
            logging.info('Done')

    def request_cloudwatch_bucket_metric_data(self, metrics_data_queries):
        """ Request CloudWatch S3 Bucket metric data, given that CloudWatch only has S3 data that is 48 hours stale.
            Requires as input a valid metrics data query"""
        date_start = datetime.today() - timedelta(days=3)
        date_end = datetime.today() - timedelta(days=2)
        client = self.cloudwatch_client
        response = client.get_metric_data(
            MetricDataQueries=metrics_data_queries,
            StartTime=date_start,
            EndTime=date_end
        )
        return response

    @staticmethod
    def cloudwatch_bucket_bytes_query(buckets):
        """ Takes in a list of S3 buckets and returns a CloudWatch query request for their size in bytes"""
        metrics_data_queries = []
        for idx, name in enumerate(buckets):
            metrics_data_queries.append({
                'Id': 'bucket_num_{}'.format(idx),
                'MetricStat': {
                    'Period': 60 * 60 * 24,  # 1 Day
                    'Stat': 'Average',
                    'Metric': {
                        'Namespace': 'AWS/S3',
                        'MetricName': 'BucketSizeBytes',
                        'Dimensions': [
                            {
                                'Name': 'BucketName',
                                'Value': name
                            },
                            {
                                'Name': 'StorageType',
                                'Value': 'StandardStorage'
                            }
                        ]
                    }
                }})
        return metrics_data_queries

    def categorize_buckets(self):
        """ Returns a tuple: a list of cgap s3 bucket names, and a list of non-cgap bucket names.
            Makes a s3 API call to retrieve the buckets in the account.
            Assumptions: s3 creds are already configured for the correct account."""
        client = self.s3_client
        response = client.list_buckets()
        cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' in i['Name']]
        not_cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' not in i['Name']]
        return cgap_buckets, not_cgap_buckets

    def update_bucket_tags(self):
        """" TODO """
        cgap_buckets, not_cgap_buckets = self.categorize_buckets()
        resource = self.s3_resource
        bucket_tagging_example = resource.BucketTagging(cgap_buckets[0])

    def delete_previous_versions(self, bucket, filename, dry_run=True):
        """ Opens the specified filename and reads in a tsv of keys. All old versions or delete-marked versions will be
            deleted. Creates a spreadsheet of the results, of what would be deleted if dry_run is True, or the delete
            calls and results if running for real, with dry_run as False.

            e.g.
            >>> delete_previous_versions(
            >>>     'elasticbeanstalk-fourfront-webprod-files', 'in/elasticbeanstalk-fourfront-webprod-files.tsv')
            >>> delete_previous_versions(
            >>>     'elasticbeanstalk-fourfront-webprod-wfoutput', 'in/elasticbeanstalk-fourfront-webprod-wfoutput.tsv')
        """
        outfile = 'out/dry_run_{}.tsv'.format(bucket) if dry_run else 'out/results_{}.tsv'.format(bucket)
        print('writing output to {}'.format(outfile))
        with open(filename, newline='') as tsvfile, open(outfile, 'w', newline='') as tsvoutfile:
            reader = csv.reader(tsvfile, delimiter='\t', quotechar='|')
            writer = csv.writer(tsvoutfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(
                ['num', 'key', 'current to be kept', 'num versions to delete', 'version keys', 'versions deleted'])

            for row in reader:
                if reader.line_num == 1:
                    continue  # skip header row while reading tsv
                object = row[0]
                deleted = row[5]
                total_versions = int(row[3])
                client = self.s3_client
                response = client.list_object_versions(Bucket=bucket, Prefix=object)  # assuming less than 100 versions
                assert response['IsTruncated'] is False, response
                ids_to_delete = []
                # important, do not delete the latest version
                dontdelete = []
                if 'Versions' in response:
                    # only get exact matches for prefix
                    versions = [v for v in response['Versions'] if v['Key'] == object]
                    dontdelete = [v['VersionId'] for v in versions if v['IsLatest'] is True]
                    assert len(dontdelete) == 0 or len(dontdelete) == 1, response
                    ids_to_delete += [v['VersionId'] for v in versions if v['IsLatest'] is not True]
                if 'DeleteMarkers' in response:
                    # only get exact matches for prefix
                    delete_markers = [d for d in response['DeleteMarkers'] if d['Key'] == object]
                    ids_to_delete += [d['VersionId'] for d in delete_markers]
                if deleted == 'TRUE' and len(dontdelete) == 0:  # latest version is delete marked so delete all
                    current = 'delete all'
                else:
                    assert len(dontdelete) == 1, response  # verify there is exactly one version to keep
                    current = dontdelete[0]
                    assert current not in ids_to_delete, response  # double check we aren't deleting current
                if dry_run:
                    writer.writerow(
                        [reader.line_num, object, current, len(ids_to_delete), ids_to_delete, 'dry run'])
                else:  # run for real, deletes objects permanently
                    deleted_ids = []
                    for version in ids_to_delete:
                        if version != 'null':  # 494 versions are 'null'...ignore these for now
                            del_res = client.delete_object(Bucket=bucket, Key=object, VersionId=version)
                        deleted_ids.append(version)
                    writer.writerow(
                        [reader.line_num, object, current, len(ids_to_delete), ids_to_delete, deleted_ids]
                    )
