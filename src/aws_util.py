import boto3
import csv
import logging
import sys

import concurrent.futures
from datetime import datetime, timedelta

from src.pricing_calculator import PricingCalculator


class AWSUtil(object):
    def __init__(self):
        """ Define the constants used by util methods."""
        self.MAIN_ACCOUNT_ID = "643366669028"
        self.BUCKET_SUMMARY_FILENAME = 'out/{}_run_results.tsv'.format(datetime.now().date())
        self.BUCKET_SUMMARY_HEADER = [
            'name', 'project tag', 'env tag', 'owner tag', 'size in bytes', 'readable size', 'estimated monthly cost']

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

    def generate_s3_bucket_summary_tsv(self, dry_run=True, upload=False):
        """ Generates a summary tsv of the S3 Buckets used by CGAP/4DN."""

        # Write the tsv to stdout if it's a dry run (to debug), otherwise write to an output file
        with open(self.BUCKET_SUMMARY_FILENAME if not dry_run else sys.stdout, 'w', newline='') as tsvfile:
            writer = csv.writer(tsvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(self.BUCKET_SUMMARY_HEADER)

            buckets_names_tags = self.get_s3_buckets_names_tags()
            response = self.get_s3_size_metric_data(buckets_names_tags)
            # Associate the response results with a bucket tags to build the column
            for idx, result in enumerate(response['MetricDataResults']):
                name, tags = buckets_names_tags[idx]
                assert name == result['Label']
                assert len(result['Timestamps']) == len(result['Values'])
                assert len(result['Values']) == 1 or len(result['Values']) == 0
                project_tag = tags['project']
                env_tag = tags['env']
                owner_tag = tags['owner']
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
        """ Generates spreadsheets of potentially useful data TODO"""
        # TODO query for this list
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
        print('Generated all csvs.')

    @staticmethod
    def make_version_responses_actionable(total_response):
        """ Take a list of responses and turn it into actionable data TODO more description"""
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
                size = 'N/A (deleted)'
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
        """ Takes a versioned bucket name, and writes a csv for all versions of the bucket
            complete_run will run the full bucket, otherwise it'll only run for the first ~1000 versions.

            TODO perhaps make complete_run configurable elsewhere
        """

        logging.basicConfig(level=logging.INFO, filename='log/{}.log'.format(bucket), filemode='a+',
                            format='%(asctime)-15s %(levelname)-8s %(message)s')
        logging.info('Starting run for {}'.format(bucket))

        client = self.s3_client()
        filename = 'out/latest_run_for_versioned_bucket_{}.tsv'.format(bucket)
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

        logging.info('Data retrieved from AWS. Making actionable...')
        actionable_data = self.make_version_responses_actionable(total_response)
        rows = [[
            'object name',
            'latest version size',
            'number of past versions',
            'total size of all versions',
            'is it deleted',
            'last modified'
        ]]
        for i in actionable_data:
            rows.append([
                actionable_data[i]['name'],
                actionable_data[i]['size'],
                actionable_data[i]['version_num'],
                actionable_data[i]['total_size'],
                actionable_data[i]['deleted'],
                actionable_data[i]['last_mod']
            ])
        logging.info('Writing spreadsheet')
        with open(filename, 'w', newline='') as tsvfile:
            writer = csv.writer(tsvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            for r in rows:
                writer.writerow(r)
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
        resource = self.s3_resource()
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
    def flatten_tag_set(self, tag_set):
        """ TODO better doctag
            Tags are converted from format [{'Key': ..., 'Value': ...}, ...]
            to format { 'env': value or '-',
                        'project': value or '-',
                        'owner': value or '-' }"""
        return {ts['Key']: ts['Value'] for ts in tag_set}

    def get_s3_buckets_names(self):
        """Returns list of bucket names"""
        return [r.name for r in self.s3_resource().buckets.all()]

    def get_s3_buckets_names_tags(self):
        """Returns (name, tags) tuple for each bucket
        """
        buckets_names_tags = []
        for r in self.s3_resource().buckets.all():
            name = r.name
            converted_tags = {}
            # Flatten tag_set, then build tag dict w/ a default value for missing required keys
            tag_set = r.Tagging().tag_set
            tag_set_flat = self.flatten_tag_set(tag_set)
            for i in ('env', 'project', 'owner'):
                converted_tags[i] = tag_set_flat.get(i, '-')
            buckets_names_tags.append((name, converted_tags))
        return buckets_names_tags

    @staticmethod
    def get_incomplete_upload_rule(self):
        """ Returns a lifecycle rule to abort incomplete multipart uploads after two weeks. See:
            https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuoverview.html#mpu-stop-incomplete-mpu-lifecycle-config
            and boto3 => S3Control.Client.put_bucket_lifecycle_configuration"""
        return {
            'ID': 'incomplete-upload-rule',
            'AbortIncompleteMultipartUpload': {
                'DaysAfterInitiation': 14
            }
        }

    def get_bucket_lifecycle_configurations(self):
        """
        Get bucket lifecycle configurations for each bucket.
        TODO: read from an input GSheet containing the lifecycles
        TODO: use these configs to update bucket lifecycle policies
        """
        bucket_lifecycle_configurations = {}
        for b in self.get_s3_buckets_names():
            bucket_lifecycle_configurations[b] = {'Rules': []}
            bucket_lifecycle_configurations[b]['Rules'].append(self.get_incomplete_upload_rule())
        return bucket_lifecycle_configurations

    def update_bucket_lifecycle_configurations(self, dry_run=True):
        client = self.s3_client()
        configs = self.get_bucket_lifecycle_configurations()
        request_kwargs = []
        for k in configs:
            kwarg = {
                'AccountId': self.MAIN_ACCOUNT_ID,
                'Bucket': k,
                'LifecycleConfiguration': configs[k]
            }
            request_kwargs.append(kwarg)
        if not dry_run:
            assert True is False, 'do not run lifecycle updates for real yet'
            [client.put_bucket_lifecycle_configuration(**r) for r in request_kwargs]
        else:
            print('dry_run: [client.put_bucket_lifecycle_configuration(**r) for r in request_kwargs]')
            print('dry_run: returning request_kwargs')
            return request_kwargs

    def get_s3_size_metric_data(self, buckets_names_tags):
        date_start = datetime.today() - timedelta(days=3)
        date_end = datetime.today() - timedelta(days=2)
        client = self.cloudwatch_client()
        metrics_data_queries = self.get_s3_size_metrics_query(buckets_names_tags)
        response = client.get_metric_data(
            MetricDataQueries=metrics_data_queries,
            StartTime=date_start,
            EndTime=date_end
        )
        return response

    @staticmethod
    def get_s3_size_metrics_query(buckets_names_tags):
        """ Constructs the metrics query for each bucket."""
        metrics_data_queries = []
        for idx, (name, tags) in enumerate(buckets_names_tags):
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

    def get_cgap_notcgap_buckets(self):
        """ Returns a tuple: a list of cgap bucket names, and a list of non-cgap bucket names.
            Makes a s3 API call to retrieve the buckets in the account.
            Assumptions: s3 creds are already configured for the correct account."""
        client = self.s3_client()
        response = client.list_buckets()
        cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' in i['Name']]
        not_cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' not in i['Name']]
        return cgap_buckets, not_cgap_buckets

    def update_tags_cgap_notcgap_buckets(self):
        """" Todo """
        cgap_buckets, not_cgap_buckets = self.get_cgap_notcgap_buckets()
        s3_resource = boto3.resouce('s3')
        bucket_tagging_example = s3_resource.BucketTagging(cgap_buckets[0])
