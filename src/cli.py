import argparse
import logging
import os

from src.info.aws_util import AWSUtil
from src.exceptions import CLIException
from src.stacks.trial import c4_stack_trial_network, c4_stack_trial_datastore, c4_stack_trial_beanstalk

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SUPPORTED_STACKS = ['c4-network-trial', 'c4-datastore-trial', 'c4-beanstalk-trial']


def provision_stack(args):
    """ Helper function for performing Cloud Formation operations on a specific stack. Ref:
        https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/best-practices.html#organizingstacks """
    if args.stack == 'c4-network-trial':
        stack = c4_stack_trial_network()
    elif args.stack == 'c4-datastore-trial':
        stack = c4_stack_trial_datastore()
    elif args.stack == 'c4-beanstalk-trial':
        stack = c4_stack_trial_beanstalk()
    else:
        raise CLIException('Unsupported stack {}. Supported Stacks: {}'.format(args.stack, SUPPORTED_STACKS))

    if args.stdout:
        stack.print_template(stdout=True)
    else:
        template_object, path, template_name = stack.print_template()
        file_path = ''.join([path, template_name])
        logger.info('Written template to {}'.format(file_path))
        if args.validate:
            cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
                mount_yaml='~/code/4dn-cloud-infra/out/templates:/root/out/templates',
                mount_creds='~/.aws_test:/root/.aws',
                command='amazon/aws-cli cloudformation validate-template',
                args='--template-body file:///root/{file_path}'.format(file_path=file_path),
            )
            logger.info('Validating provisioned template...')
            os.system(cmd)

        if args.upload_change_set:
            cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
                mount_yaml='~/code/4dn-cloud-infra/out/templates:/root/out/templates',
                mount_creds='~/.aws_test:/root/.aws',
                command='amazon/aws-cli cloudformation deploy',
                args='--template-file /root/{file_path} --stack-name {stack_name} --no-execute-changeset'.format(
                    file_path=file_path, stack_name=stack.name.stack_name),
            )

            logger.info('Uploading provisioned template and generating changeset...')
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
    parser.add_argument('--debug', action='store_true', help='Sets log level to debug')
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    # Configure 'provision' command
    # TODO flag for log level
    parser_provision = subparsers.add_parser('provision', help='Provisions cloud resources for CGAP/4DN')
    parser_provision.add_argument('stack', help='Select stack to operate on: {}'.format(SUPPORTED_STACKS))
    parser_provision.add_argument('--stdout', action='store_true', help='Writes template to STDOUT only')
    parser_provision.add_argument('--validate', action='store_true', help='Verifies template')
    parser_provision.add_argument('--upload_change_set', action='store_true',
                                  help='Uploads template and provisions change set')
    parser_provision.set_defaults(func=provision_stack)

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
    if args.debug:
        logger.setLevel(logging.DEBUG)
        logger.debug('Debug mode enabled')
    else:
        logger.setLevel(logging.INFO)
    if args.command:
        args.func(args)
        logger.info('Command completed, exiting..')
    else:
        logger.info('Select a command, run with -h to list them, exiting..')
