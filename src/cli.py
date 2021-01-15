import argparse
import logging
import os

from src.aws_util import AWSUtil
from src.infra import C4InfraTrial
from src.exceptions import CLIException

""" TODO Q's:
    1) 'TypeError: Object of type 'method' is not JSON serializable' findable via `to_dict` reply..add to execption?
    2) 'Ref' subclass to execute method (and possibly add to dependency graph for meta-analysis + AWS drawing?) 
    4) method types...i.e. for
        def write_outfile(text: Any,
            outfile: Any) -> None 
    5) tests -- a. if a resource has a classmethod but isn't in a mk method, raise error?
                b. try to make each individual resource or 'mk_*' method...catch exceptions pushed to a branch...
                   ...could also do the template upload + change set creation via CI hook, with the apply done via CLI.
"""


def generate_template(args, env=None, current_version='2021-01-15-cgap-trial-01'):
    """ Generates the template for CGAPTrial.
        TODO support other environments/stacks:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/best-practices.html#organizingstacks """
    if env:
        raise CLIException('envs other than CGAPTrial not supported')
    outfile = 'out/cf-yml/{}.yml'.format(current_version)
    C4InfraTrial().generate_template(outfile=outfile)
    if args.validate:
        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
            mount_yaml='~/code/4dn-cloud-infra/out/cf-yml:/root/out/cf-yml',
            mount_creds='~/.aws_test:/root/.aws',
            command='amazon/aws-cli cloudformation validate-template',
            args='--template-body file:///root/{outfile}'.format(outfile=outfile),
        )
        logging.info('Validating generated template...')
        os.system(cmd)

    if args.upload:
        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
            mount_yaml='~/code/4dn-cloud-infra/out/cf-yml:/root/out/cf-yml',
            mount_creds='~/.aws_test:/root/.aws',
            command='amazon/aws-cli cloudformation deploy',
            args='--template-file /root/{outfile} --stack-name {stack_name} --no-execute-changeset'.format(
                outfile=outfile, stack_name=C4InfraTrial.STACK_NAME),
        )

        logging.info('Uploading generated template and generating change-set...')
        if '--no-execute-changeset' not in cmd:
            raise CLIException(
                'Upload command must include no-execute-changeset, or the changes will be executed immediately')
        os.system(cmd)

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


def cli():
    """Set up and run the 4dn cloud infra command line scripts"""
    logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)-8s %(message)s')
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    # Configure 'generate' command
    # TODO flag to select env
    # TODO flag for log level
    # TODO flag for verifying and saving template
    parser_generate = subparsers.add_parser('generate', help='Generate Cloud Formation template for CGAP Trial env')
    parser_generate.add_argument('--validate', action='store_true', help='Verifies template')
    parser_generate.add_argument('--upload', action='store_true', help='Uploads template and generates change set')
    parser_generate.set_defaults(func=generate_template)

    # TODO command for Cloud Formation deploy flow: upload, verify, execute

    # Configure 'cost' command
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
        logging.info('Complete')
    else:
        logging.info('Select a command, run with -h for help')
