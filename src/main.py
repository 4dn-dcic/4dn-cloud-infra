import argparse
import boto3
import csv

from datetime import datetime, timedelta


def generate_template(args):
    print('TBD')


def get_cloudwatch_client():
    return boto3.client('cloudwatch')


def get_s3_resource():
    return boto3.resource('s3')


def get_s3_client():
    return boto3.client('s3')


def exchange_for_full_tier_1_use(size_bytes, size_price):
    size_bytes = size_bytes - 54_975_581_388_800.0  # standard_tier_1['size'] * tib
    size_price = size_price + 1177.6  # standard_tier_1['size'] * tib / gib * standard_tier_1['cost']
    return size_bytes, size_price


def exchange_for_full_tier_2_use(size_bytes, size_price):
    size_bytes = size_bytes - 494_780_232_499_200.0  # standard_tier_2['size'] * tib
    size_price = size_price + 10_137.599999999999  # standard_tier_2['size'] * tib / gib * standard_tier_2['cost']
    return size_bytes, size_price


def convert_size_bytes_to_price(size_bytes):
    size_price = 0  # In USD, to be converted to price format at end
    # Using gib and tib as GiB and TiB, given that:
    # 1 KiB = 1024 Bytes = 2**10
    # 1 MiB = 1048576 Bytes = 2**20
    gib = 1_073_741_824.0  # float(2**30)
    tib = 1_099_511_627_776.0  # float(2**40)
    # Tier Pricing: size in TiB, cost in GiB
    standard_tier_1 = {'size': 50.0, 'cost': 0.023}
    standard_tier_2 = {'size': 450.0, 'cost': 0.022}
    standard_tier_3 = {'size': 500.0, 'cost': 0.021}
    if size_bytes <= standard_tier_1['size'] * tib:
        size_price = (size_bytes / gib) * standard_tier_1['cost']
    elif size_bytes <= standard_tier_2['size'] * tib:
        size_bytes, size_price = exchange_for_full_tier_1_use(size_bytes, size_price)
        size_price += (size_bytes / gib) * standard_tier_2['cost']
    elif size_bytes > standard_tier_3['size'] * tib:
        size_bytes, size_price = exchange_for_full_tier_1_use(size_bytes, size_price)
        size_bytes, size_price = exchange_for_full_tier_2_use(size_bytes, size_price)
        size_price += (size_bytes / gib) * standard_tier_3['cost']
    else:
        raise Exception()
    return '${:,.2f}'.format(size_price)


def convert_size_bytes_to_readable(size_bytes):
    if size_bytes >= 1_000_000_000_000.0:
        size_readable = '{} TB'.format(round(size_bytes / 1_000_000_000_000.0, 2))
    elif size_bytes >= 1_000_000_000.0:
        size_readable = '{} GB'.format(round(size_bytes / 1_000_000_000.0, 2))
    elif size_bytes >= 1_000_000.0:
        size_readable = '{} MB'.format(round(size_bytes / 1_000_000.0, 2))
    elif size_bytes >= 1_000.0:
        size_readable = '{} KB'.format(round(size_bytes / 1_000.0, 2))
    else:
        size_readable = '{} Bytes'.format(round(size_bytes, 2))
    return size_readable


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


def generate_csv_of_all_versioned_files_for_bucket(bucket='elasticbeanstalk-fourfront-webprod-wfoutput'):
    """Takes a versioned bucket name, and writes a csv for all versions of the bucket
    (TBD: truncation support)"""
    rows = [[
        'bucket name',  # str
        'entity tag or delete marker',  # ETag of version or 'delete marker' str for all delete markers
        'size in bytes',  # int
        'storage class',  # 'STANDARD'
        'object key',  # str of path to object
        'object version id',  # str
        'owner display name',  # str
        'is latest',  # bool
        'last modified'  # str(datetime obj)
    ]]
    client = get_s3_client()
    filename = 'latest_run_for_versioned_bucket_{}.csv'.format(bucket)
    # TODO handle truncation with multiple requests
    # TODO verify the spreadsheet format before handling truncation (~55k requests)
    response = make_list_object_versions_request(client, bucket)
    for version in response['Versions']:
        rows.append([
            bucket,
            version['ETag'],
            version['Size'],
            version['StorageClass'],
            version['Key'],
            version['VersionId'],
            version['Owner']['DisplayName'],
            version['IsLatest'],
            str(version['LastModified'])
            ])
    for marker in response['DeleteMarkers']:
        rows.append([
            bucket,
            'delete marker',
            'N/A',
            'N/A',
            marker['Key'],
            marker['VersionId'],
            marker['IsLatest'],
            str(marker['LastModified'])
            ])
    with open(filename, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter='\t', quotechar='|', quoting=csv.QUOTE_MINIMAL)
        for r in rows:
            writer.writerow(r)


def get_s3_buckets_names_tags():
    """Returns (name, tags) tuple for each bucket
    Tags are converted from format [{'Key': ..., 'Value': ...}, ...]
    to format { 'env': value or '-',
                'project': value or '-',
                'owner': value or '-' }
    """
    buckets_names_tags = []
    resource = get_s3_resource()
    for r in resource.buckets.all():
        name = r.name
        converted_tags = {}
        # Flatten tag_set, then build tag dict w/ a default value for missing required keys
        tag_set = r.Tagging().tag_set
        tag_set_flat = {ts['Key']: ts['Value'] for ts in tag_set}
        for i in ('env', 'project', 'owner'):
            converted_tags[i] = tag_set_flat.get(i, '-')
        buckets_names_tags.append((name, converted_tags))
    return buckets_names_tags


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
            'Period': 60*60*24,  # 1 Day
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
