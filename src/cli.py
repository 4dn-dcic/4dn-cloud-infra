import argparse
import logging
import os

from src.aws_util import AWSUtil
from src.exceptions import CLIException
from src.stacks.trial import c4_stack_trial_network, c4_stack_trial_datastore, c4_stack_trial_beanstalk

logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)-8s %(message)s')
logger = logging.getLogger(__name__)


def generate_template(args):
    """ Generates the template for CGAPTrial.
        TODO support other environments/parts:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/best-practices.html#organizingstacks """
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    if args.env == 'c4-network-trial':
        stack = c4_stack_trial_network()
    elif args.env == 'c4-datastore-trial':
        stack = c4_stack_trial_datastore()
    elif args.env == 'c4-beanstalk-trial':
        stack = c4_stack_trial_beanstalk()
    else:
        raise CLIException('envs other than c4-{network, datastore, beanstalk}-trial not yet supported')

    if args.stdout:
        stack.print_template(stdout=True)
    else:
        outfile = stack.print_template()
        if args.validate:
            cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
                mount_yaml='~/code/4dn-cloud-infra/out/cf-yml:/root/out/cf-yml',
                mount_creds='~/.aws_test:/root/.aws',
                command='amazon/aws-cli cloudformation validate-template',
                args='--template-body file:///root/{outfile}'.format(outfile=outfile),
            )
            logger.info('Validating generated template...')
            os.system(cmd)

        if args.upload_change_set:
            cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
                mount_yaml='~/code/4dn-cloud-infra/out/cf-yml:/root/out/cf-yml',
                mount_creds='~/.aws_test:/root/.aws',
                command='amazon/aws-cli cloudformation deploy',
                args='--template-file /root/{outfile} --stack-name {stack_name} --no-execute-changeset'.format(
                    outfile=outfile, stack_name=stack.name.stack_name),
            )

            logger.info('Uploading generated template and generating change-set...')
            if '--no-execute-changeset' not in cmd:
                raise CLIException(
                    'Upload command must include no-execute-changeset, or the changes will be executed immediately')
            os.system(cmd)


def info(args):
    aws_util = AWSUtil()
    if args.upload and args.versioned:
        # TODO add GSheet functionality as a src util
        logger.info('Use ./bin/upload_vspreadsheets.py to upload versioned s3 spreadsheets')
    if args.versioned:
        logger.info('Generating versioned s3 buckets summary tsv...')
        aws_util.generate_versioned_files_summary_tsvs()
    if args.s3:
        logger.info('Generating s3 buckets info summary tsv at {}...'.format(aws_util.BUCKET_SUMMARY_FILENAME))
        aws_util.generate_s3_bucket_summary_tsv(dry_run=False)


def cli():
    """Set up and run the 4dn cloud infra command line scripts"""
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    # Configure 'generate' command
    # TODO flag for log level
    parser_generate = subparsers.add_parser('generate', help='Generate Cloud Formation template for CGAP Trial env')
    parser_generate.add_argument('env', help='Select stack to operate on')
    parser_generate.add_argument('--stdout', action='store_true', help='Writes template to STDOUT only')
    parser_generate.add_argument('--debug', action='store_true', help='Sets log level to debug')
    parser_generate.add_argument('--validate', action='store_true', help='Verifies template')
    parser_generate.add_argument('--upload_change_set', action='store_true',
                                 help='Uploads template and generates change set')
    parser_generate.set_defaults(func=generate_template)

    # TODO command for Cloud Formation deploy flow: execute_change_set

    # Configure 'info' command
    parser_info = subparsers.add_parser('info', help='Generate informational summaries for 4DN accounts')
    parser_info.add_argument('--s3', action='store_true', help='Generate S3 buckets cost summary')
    parser_info.add_argument('--versioned', action='store_true', help='Generate versioned S3 buckets cost summary')
    # TODO add summaries of other aws info types
    parser_info.add_argument('--all', action='store_true', help='Generate all cost summary spreadsheets')
    parser_info.add_argument('--upload', action='store_true', help='Upload spreadsheets to Google Sheets')
    parser_info.set_defaults(func=info)

    args = parser.parse_args()
    if args.command:
        args.func(args)
        logger.info('Complete')
    else:
        logger.info('Select a command, run with -h for help')
