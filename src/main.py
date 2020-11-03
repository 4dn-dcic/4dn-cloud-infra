import argparse
import boto3
import csv
import logging

import concurrent.futures

from datetime import datetime, timedelta


def generate_template(args):
    print('TBD')



def generate_csv_of_current_s3_bucket_size_and_metadata():
    filename = 'latest_run_results.csv'
    rows = [
        ['name', 'project tag', 'env tag', 'owner tag', 'size in bytes', 'readable size', 'estimated monthly cost']
    ]
    buckets_names_tags = get_s3_buckets_names_tags()
    response = get_s3_size_metric_data(buckets_names_tags)
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
            size_readable = convert_size_bytes_to_readable(size_bytes)
            size_price = convert_size_bytes_to_price(size_bytes)
        rows.append([name, project_tag, env_tag, owner_tag, size_bytes, size_readable, size_price])

    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            writer.writerow(r)


def make_list_object_versions_request(client, bucket, follow_up_request=False,
                                      next_key_marker=None, next_version_id_marker=None):
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


def generate_csvs_for_all_versioned_buckets():
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
        executor.map(generate_csv_of_all_versioned_files_for_bucket, versioned_buckets, chunksize=4)
    print('Generated all csvs.')


def make_version_responses_actionable(total_response):
    """Take a list of responses and turn it into actionable data"""
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


def generate_csv_of_all_versioned_files_for_bucket(bucket='elasticbeanstalk-fourfront-webprod-wfoutput',
                                                   complete_run=True):
    """Takes a versioned bucket name, and writes a csv for all versions of the bucket
    complete_run will run the full bucket, otherwise it'll only run for the first ~1000 versions.
    # TODO perhaps make complete_run configurable elsewhere
    """

    logging.basicConfig(level=logging.INFO, filename='log/{}.log'.format(bucket), filemode='a+',
                        format='%(asctime)-15s %(levelname)-8s %(message)s')
    logging.info('Starting run for {}'.format(bucket))

    client = get_s3_client()
    filename = 'out/latest_run_for_versioned_bucket_{}.tsv'.format(bucket)
    # Excel cares about the filename for import, GSheets doesn't care

    logging.info('Generating csv for {}'.format(bucket))
    logging.info('Retrieving data from AWS...')
    first_response = make_list_object_versions_request(client, bucket)
    total_response = [first_response]

    if complete_run:
        logging.info('Retrieving data chunks in a loop..')
        while total_response[-1]['IsTruncated']:
            next_key_marker = total_response[-1]['NextKeyMarker']
            next_version_id_marker = total_response[-1]['NextVersionIdMarker']
            next_response = make_list_object_versions_request(client, bucket, True,
                                                              next_key_marker=next_key_marker,
                                                              next_version_id_marker=next_version_id_marker
                                                              )
            total_response.append(next_response)

    logging.info('Data retrieved from AWS. Making actionable...')
    actionable_data = make_version_responses_actionable(total_response)
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
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            writer.writerow(r)
    logging.info('wrote {}'.format(filename))

def update_tags_from_input_csv(dry_run=True):
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
    resource = get_s3_resource()
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


def flatten_tag_set(tag_set):
    """Tags are converted from format [{'Key': ..., 'Value': ...}, ...]
    to format { 'env': value or '-',
                'project': value or '-',
                'owner': value or '-' }"""
    return {ts['Key']: ts['Value'] for ts in tag_set}


def get_s3_buckets_names():
    """Returns list of bucket names"""
    resource = get_s3_resource()
    return [r.name for r in resource.buckets.all()]


def get_s3_buckets_names_tags():
    """Returns (name, tags) tuple for each bucket
    """
    buckets_names_tags = []
    resource = get_s3_resource()
    for r in resource.buckets.all():
        name = r.name
        converted_tags = {}
        # Flatten tag_set, then build tag dict w/ a default value for missing required keys
        tag_set = r.Tagging().tag_set
        tag_set_flat = flatten_tag_set(tag_set)
        for i in ('env', 'project', 'owner'):
            converted_tags[i] = tag_set_flat.get(i, '-')
        buckets_names_tags.append((name, converted_tags))
    return buckets_names_tags


def get_incomplete_upload_rule():
    """returns a lifecycle rule to abort incomplete multipart uploads after two weeks
    See: https://docs.aws.amazon.com/AmazonS3/latest/dev/mpuoverview.html#mpu-stop-incomplete-mpu-lifecycle-config
    and boto3 => S3Control.Client.put_bucket_lifecycle_configuration"""
    return {
        'ID': 'incomplete-upload-rule',
        'AbortIncompleteMultipartUpload': {
            'DaysAfterInitiation': 14
        }
    }


def get_bucket_lifecycle_configurations():
    """
    Get bucket lifecycle configurations for each bucket.
    TODO: read from an input GSheet containing the lifecycles
    TODO: use these configs to update bucket lifecycle policies
    """
    bucket_lifecycle_configurations = {}
    for b in get_s3_buckets_names():
        bucket_lifecycle_configurations[b] = {'Rules': []}
        bucket_lifecycle_configurations[b]['Rules'].append(get_incomplete_upload_rule())
    return bucket_lifecycle_configurations


def update_bucket_lifecycle_configurations(dry_run=True):
    client = get_s3_client()
    configs = get_bucket_lifecycle_configurations()
    request_kwargs = []
    for k in configs:
        kwarg = {
            'AccountId': MAIN_ACCOUNT_ID,
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


def get_s3_size_metric_data(buckets_names_tags):
    date_start = datetime.today() - timedelta(days=3)
    date_end = datetime.today() - timedelta(days=2)
    client = get_cloudwatch_client()
    metrics_data_queries = get_s3_size_metrics_query(buckets_names_tags)
    response = client.get_metric_data(
        MetricDataQueries=metrics_data_queries,
        StartTime=date_start,
        EndTime=date_end
    )
    return response


def get_s3_size_metrics_query(buckets_names_tags):
    """ Constructs the metrics query for each bucket."""
    metrics_data_queries = []
    for idx, (name, tags) in enumerate(buckets_names_tags):
        query = {}
        query['Id'] = 'bucket_num_{}'.format(idx)
        query['MetricStat'] = {
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
        }
        metrics_data_queries.append(query)
    return metrics_data_queries


def get_cgap_notcgap_buckets():
    """Returns a tuple: a list of cgap bucket names, and a list of non-cgap bucket names.
        Makes a s3 API call to retrieve the buckets in the account.
        Assumptions: s3 creds are already configured for the correct account."""
    s3_client = boto3.client('s3')
    response = s3_client.list_buckets()
    cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' in i['Name']]
    not_cgap_buckets = [i['Name'] for i in response['Buckets'] if 'cgap' not in i['Name']]
    return cgap_buckets, not_cgap_buckets


def update_tags_cgap_notcgap_buckets():
    cgap_buckets, not_cgap_buckets = get_cgap_notcgap_buckets()
    s3_resource = boto3.resouce('s3')
    bucket_tagging_example = s3_resource.BucketTagging(cgap_buckets[0])


def costs(args):
    print('TBD, run generate_csv_of_current_s3_bucket_size_and_metadata() in python console to generate csv')


def main():
    # TODO logging
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    parser_generate = subparsers.add_parser('generate', help='Generate Cloud Formation template as json')
    parser_generate.set_defaults(func=generate_template)

    parser_cost = subparsers.add_parser('cost', help='Manage cost accounting scripts for 4DN accounts')
    parser_cost.set_defaults(func=costs)

    args = parser.parse_args()
    if args.command:
        args.func(args)
    else:
        print('Select a command, run with -h for help')


if __name__ == '__main__':
    main()
