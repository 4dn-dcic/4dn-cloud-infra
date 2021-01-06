import argparse
import logging

from src.aws_util import AWSUtil
from src.infra import create_new_account_template


def generate_template(args):
    # TODO(berg): as account migration proceeds, rename from create_new -> create_$actualname
    template = create_new_account_template()
    print(template.to_json())


def costs(args):
    aws_util = AWSUtil()
    if args.upload and args.versioned:
        # TODO add GSheet functionality as a src util
        logging.info('Use ./bin/upload_vspreadsheets.py to upload versioned s3 spreadsheets')
    if args.versioned:
        logging.info('Generating versioned s3 buckets summary tsv...')
        aws_util.generate_versioned_files_summary_tsvs()
    if args.s3:
        logging.info('Generating s3 buckets cost summary tsv at {}...'.format(aws_util.BUCKET_SUMMARY_FILENAME))
        aws_util.generate_s3_bucket_summary_tsv(dry_run=False)
    logging.info('Complete')


def main():
    """Set up and run the 4dn cloud infra command line scripts"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)-8s %(message)s')
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    parser_generate = subparsers.add_parser('generate', help='Generate Cloud Formation template as json')
    parser_generate.set_defaults(func=generate_template)

    parser_cost = subparsers.add_parser('cost', help='Generate cost summary spreadsheets for 4DN accounts')
    parser_cost.add_argument('--s3', action='store_true', help='Generate S3 buckets cost summary')
    parser_cost.add_argument('--versioned', action='store_true', help='Generate versioned S3 buckets cost summary')
    # TODO add summaries of other aws cost types
    parser_cost.add_argument('--all', action='store_true', help='Generate all cost summary spreadsheets')
    parser_cost.add_argument('--upload', action='store_true', help='Upload spreadsheets to Google Sheets')
    parser_cost.set_defaults(func=costs)

    args = parser.parse_args()
    if args.command:
        args.func(args)
    else:
        logging.info('Select a command, run with -h for help')


if __name__ == '__main__':
    main()
