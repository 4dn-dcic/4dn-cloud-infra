import argparse
import logging
import os

from src.info.aws_util import AWSUtil
from src.exceptions import CLIException
from src.stacks.trial import (
    c4_stack_trial_account,
    c4_stack_trial_network,
    c4_stack_trial_network_metadata,
    c4_stack_trial_datastore,
    c4_stack_trial_beanstalk,
    c4_stack_trial_tibanna,
)
from src.stacks.trial_alpha import (
    c4_alpha_stack_trial_metadata,
    c4_alpha_stack_trial_network,
    c4_ecs_stack_trial_datastore,
    c4_alpha_stack_trial_iam,
    c4_alpha_stack_trial_ecr,
    c4_alpha_stack_trial_logging,
    c4_alpha_stack_trial_ecs
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# TODO constants
SUPPORTED_STACKS = ['c4-network-trial', 'c4-datastore-trial', 'c4-beanstalk-trial', 'c4-tibanna-trial']
SUPPORTED_ECS_STACKS = ['c4-ecs-network-trial', 'c4-ecs-datastore-trial', 'c4-ecs-cluster-trial']
AWS_REGION = 'us-east-1'


class C4Client:
    """ Client class for interacting with and provisioning CGAP Infrastructure as Code. """
    ALPHA_LEAF_STACKS = ['iam', 'logging', 'network']  # stacks that only export values
    ACCOUNT = c4_stack_trial_account()  # uses creds for trial account access
    CAPABILITY_IAM = 'CAPABILITY_IAM'
    REQUIRES_CAPABILITY_IAM = ['iam']  # these stacks require CAPABILITY_IAM, just IAM for now

    def validate_cloudformation_template(self, file_path):
        """ Validates CloudFormation template at file_path """
        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
            mount_yaml=os.path.abspath(os.getcwd())+'/out/templates:/root/out/templates',
            mount_creds='{creds_dir}:/root/.aws'.format(creds_dir=self.ACCOUNT.creds_dir),
            command='amazon/aws-cli cloudformation validate-template',
            args='--template-body file://{file_path}'.format(file_path=file_path),
        )
        logger.info('Validating provisioned template...')
        os.system(cmd)

    @staticmethod
    def build_template_flag(*, file_path):
        return '--template-file {file_path}'.format(file_path=file_path)

    @staticmethod
    def build_stack_flag(*, stack_name):
        return '--stack-name {stack_name}'.format(stack_name=stack_name)

    @staticmethod
    def build_parameter_override(*, param_name, value):
        return '"{param}={stack}"'.format(param=param_name, stack=value)

    @staticmethod
    def build_flags(*, template_flag, stack_flag, parameter_flags, changeset_flag='--no-execute-changeset',
                    capability_flags):
        return '{template_flag} {stack_flag} {parameter_flag} {changeset_flag} {capability_flags}'.format(
            template_flag=template_flag,
            stack_flag=stack_flag,
            parameter_flag=parameter_flags,
            changeset_flag=changeset_flag,
            capability_flags=capability_flags
        )

    @staticmethod
    def build_changeset_flags():
        pass  # implement if needed

    @classmethod
    def build_capability_param(cls, stack, name=CAPABILITY_IAM):
        caps = ''
        for possible in cls.REQUIRES_CAPABILITY_IAM:
            if possible in stack.name.stack_name:
                caps = '--capabilities %s' % name
                break
        return caps

    @classmethod
    def upload_cloudformation_template(cls, args, stack, file_path):
        if cls.is_legacy(args):
            network_stack_name, _ = c4_stack_trial_network_metadata()

            parameter_flags = [
                '--parameter-overrides',  # the flag itself
                cls.build_parameter_override(param_name='NetworkStackNameParameter',
                                             value=network_stack_name.stack_name),
            ]

            flags = cls.build_flags(
                template_flag=cls.build_template_flag(file_path=file_path),
                stack_flag=cls.build_stack_flag(stack_name=stack.name.stack_name),
                parameter_flags=' '.join(parameter_flags),
                capability_flags=cls.build_capability_param(stack),  # defaults to IAM
            )
        else:
            network_stack_name, _ = c4_alpha_stack_trial_metadata(name='network')  # XXX: constants
            iam_stack_name, _ = c4_alpha_stack_trial_metadata(name='iam')
            ecr_stack_name, _ = c4_alpha_stack_trial_metadata(name='ecr')
            # TODO incorporate datastore output to ECS stack
            datastore_stack_name, _ = c4_alpha_stack_trial_metadata(name='datastore')

            # if we are building a leaf stack, our upload doesn't require these parameter overrides
            # since we are not importing values from other stacks
            if stack.name.stack_name in cls.ALPHA_LEAF_STACKS:
                parameter_flags = ''
            else:
                parameter_flags = [
                    '--parameter-overrides',  # the flag itself
                    cls.build_parameter_override(param_name='NetworkStackNameParameter',
                                                 value=network_stack_name.stack_name),
                    cls.build_parameter_override(param_name='ECRStackNameParameter',
                                                 value=ecr_stack_name.stack_name),
                    cls.build_parameter_override(param_name='IAMStackNameParameter',
                                                 value=iam_stack_name.stack_name),
                    # cls.build_parameter_override(param_name='DatastoreStackNameParameter',
                    #                              value=datastore_stack_name.stack_name)
                ]
            flags = cls.build_flags(
                template_flag=cls.build_template_flag(file_path=file_path),
                stack_flag=cls.build_stack_flag(stack_name=stack.name.stack_name),
                parameter_flags=' '.join(parameter_flags),
                capability_flags=cls.build_capability_param(stack)  # defaults to IAM
            )

        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {flags}'.format(
            mount_yaml=os.path.abspath(os.getcwd())+'/out/templates:/root/out/templates',
            mount_creds='{creds_dir}:/root/.aws'.format(creds_dir=stack.account.creds_dir),
            command='amazon/aws-cli cloudformation deploy',
            flags=flags,
        )
        logger.info(cmd)
        logger.info('Uploading provisioned template and generating changeset...')
        if '--no-execute-changeset' not in cmd:
            raise CLIException(
                'Upload command must include no-execute-changeset, or the changes will be executed immediately')
        os.system(cmd)

    @staticmethod
    def is_legacy(args):
        """ 'legacy' in this case is beanstalk """
        if args.alpha:
            return False
        return True

    @staticmethod
    def resolve_alpha_stack(args):
        """ Figures out which stack to run in the ECS case. """
        if 'network' in args.stack:
            stack = c4_alpha_stack_trial_network()
        elif 'datastore' in args.stack:
            stack = c4_ecs_stack_trial_datastore()
        elif 'ecr' in args.stack:
            stack = c4_alpha_stack_trial_ecr()
        elif 'iam' in args.stack:
            stack = c4_alpha_stack_trial_iam()
        elif 'logging' in args.stack:
            stack = c4_alpha_stack_trial_logging()
        elif 'ecs' in args.stack:
            stack = c4_alpha_stack_trial_ecs()
        elif args.stack == 'all':
            raise NotImplementedError('TODO')
        else:
            raise CLIException('Could not find suitable match for specified stack')
        return stack

    @staticmethod
    def resolve_legacy_stack(args):
        if args.stack == 'c4-network-trial':
            stack = c4_stack_trial_network()
        elif args.stack == 'c4-datastore-trial':
            stack = c4_stack_trial_datastore()
        elif args.stack == 'c4-beanstalk-trial':
            stack = c4_stack_trial_beanstalk()
        elif args.stack == 'c4-tibanna-trial':
            stack = c4_stack_trial_tibanna()
        elif args.stack in SUPPORTED_STACKS:
            raise CLIException('Supported stack {} requires a resolver in `resolve_legacy_stack`'.format(args.stack))
        else:
            raise CLIException('Unsupported stack {}. Supported Stacks: {}'.format(args.stack, SUPPORTED_STACKS))
        return stack

    @classmethod
    def write_and_validate_template(cls, args, stack):
        """ Writes and validates the generated cloudformation template
            Note that stdout does not validate, making it not very useful.
        """
        if args.stdout:
            stack.print_template(stdout=True)
            exit(0)  # if this is specified, we definitely don't want to upload
        else:
            template_object, path, template_name = stack.print_template()
            file_path = ''.join(['/root/', path, template_name])
            logger.info('Written template to {}'.format(file_path))
            if args.validate:
                cls.validate_cloudformation_template(file_path)
            return file_path

    @staticmethod
    def view_changes(args):
        # TODO implement me
        if args.view_changes:
            # fetch current template from cloudformation, convert to json
            # generate current template as json
            # view and print diffs
            logger.info('I do nothing right now!')  # dcic_utils.diff_utils.

    @classmethod
    def provision_stack(cls, args):
        """ Implements 'provision' command. """
        if cls.is_legacy(args):
            stack = cls.resolve_legacy_stack(args)
        else:
            stack = cls.resolve_alpha_stack(args)

        file_path = cls.write_and_validate_template(args, stack)  # could exit if stdout arg is provided
        cls.view_changes(args)  # does nothing as of right now
        if args.upload_change_set:
            cls.upload_cloudformation_template(args, stack, file_path)  # if desired

    @classmethod
    def manage_tibanna(cls, args):
        """ Implements 'tibanna' command. """
        cmd = 'tibanna --help'
        os.system(cmd)

    @staticmethod
    def info(args):
        """ Implements 'info' command """
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
    parser_provision.add_argument('--alpha', action='store_true', help='Triggers building of the Alpha (ECS) stack',
                                  default=False)
    parser_provision.add_argument('--stdout', action='store_true', help='Writes template to STDOUT only')
    parser_provision.add_argument('--validate', action='store_true', help='Verifies template')
    parser_provision.add_argument('--view_changes', action='store_true', help='TBD: view changes made to template')
    parser_provision.add_argument('--upload_change_set', action='store_true',
                                  help='Uploads template and provisions change set')
    parser_provision.set_defaults(func=C4Client.provision_stack)

    # TODO command for Cloud Formation deploy flow: execute_change_set

    # Configure 'tibanna' command, for managing a tibanna installation on cloud infrastructure
    parser_tibanna = subparsers.add_parser('tibanna', help='Helps manage and provision tibanna for CGAP/4DN')
    parser_tibanna.add_argument('exec', help='Runs the tibanna command-line for the trial account')
    parser_tibanna.set_defaults(func=C4Client.manage_tibanna)

    # Configure 'info' command
    parser_info = subparsers.add_parser('info', help='Generate informational summaries for 4DN accounts')
    parser_info.add_argument('--s3', action='store_true', help='Generate S3 buckets cost summary')
    parser_info.add_argument('--versioned', action='store_true', help='Generate versioned S3 buckets cost summary')
    # TODO add summaries of other aws info types
    parser_info.add_argument('--all', action='store_true', help='Generate all cost summary spreadsheets')
    parser_info.add_argument('--upload', action='store_true', help='Upload spreadsheets to Google Sheets')
    parser_info.set_defaults(func=C4Client.info)

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
