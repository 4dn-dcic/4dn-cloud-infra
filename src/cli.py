import argparse
import logging
import os
# import json

# from contextlib import contextmanager
from dcicutils.misc_utils import ignored  # , file_contents, override_environ
from .constants import (
    # DEPLOYING_IAM_USER, ENV_NAME,
    ACCOUNT_NUMBER,
    # S3_ENCRYPT_KEY
)
from .info.aws_util import AWSUtil
from .base import lookup_stack_creator, ConfigManager
from .exceptions import CLIException
from .part import C4Account
from .stack import C4FoursightCGAPStack
# from .stacks.trial import c4_stack_trial_network_metadata, c4_stack_trial_tibanna
from .stacks.trial_alpha import c4_alpha_stack_trial_metadata


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# TODO constants
SUPPORTED_ECS_STACKS = ['c4-ecs-network-trial', 'c4-ecs-datastore-trial', 'c4-ecs-cluster-trial']
AWS_REGION = 'us-east-1'


class C4Client:
    """ Client class for interacting with and provisioning CGAP Infrastructure as Code. """
    ALPHA_LEAF_STACKS = ['iam', 'logging', 'network']  # stacks that only export values
    CAPABILITY_IAM = 'CAPABILITY_IAM'
    SUPPORTED_STACKS = ['c4-network-trial', 'c4-datastore-trial', 'c4-tibanna-trial', 'c4-foursight-trial',
                        'c4-beanstalk-trial']
    REQUIRES_CAPABILITY_IAM = ['iam', 'foursight']  # these stacks require CAPABILITY_IAM, just IAM for now
    # CONFIGURATION = 'config.json'  # path to config file, top level by default

    @classmethod
    def validate_cloudformation_template(cls, file_path):  # , creds_dir=None
        """ Validates CloudFormation template at file_path """
        creds_dir = (  # creds_dir or
                     ConfigManager.get_creds_dir())
        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {args}'.format(
            mount_yaml=os.path.abspath(os.getcwd())+'/out/templates:/root/out/templates',
            mount_creds=f'{creds_dir}:/root/.aws',
            command='amazon/aws-cli cloudformation validate-template',
            args=f'--template-body file://{file_path}',
        )
        logger.info('Validating provisioned template...')
        os.system(cmd)

    @staticmethod
    def build_template_flag(*, file_path):
        return f'--template-file {file_path}'

    @staticmethod
    def build_stack_flag(*, stack_name):
        return f'--stack-name {stack_name}'

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

    # APPLICATION_BUCKET_TEMPLATE = "foursight-{org_prefix}{env_name}-applicaton-versions"

    @classmethod
    def upload_chalice_package(cls, args, stack: C4FoursightCGAPStack, bucket=None):
        """ Specific upload process for a chalice application, e.g. foursight. Assumes chalice package has been run.
            How this works:
            1. Mounts the output_file directory to the docker image's execution directory (/root/aws)
            2. Runs aws cloudformation package, which uploads the deploy artifact to the s3 bucket
            3. This command generates a cloudformation template, which is saved to the local deploy artifact directory
            4. Runs aws cloudformation deploy, which generates a changeset based on this generated cloudformation.
        """

        # TODO: this bucketname should come from config.json or some os.environ ...
        if bucket is None:
            bucket = ConfigManager.resolve_bucket_name(ConfigManager.FSBucketTemplate.APPLICATION_VERSIONS)  # cls.APPLICATION_BUCKET_TEMPLATE

        creds_dir = ConfigManager.get_creds_dir()  # was args.creds_dir

        # Mounts the output_file directory to the docker image's execution directory (/root/aws)
        mount_chalice_package = '{}/{}:/aws'.format(os.path.abspath(os.getcwd()), args.output_file)
        # Creates mount point flags for creds and the chalice package
        mount_points = ' '.join([
                '-v',
                f'{creds_dir}:/root/.aws',  # was args.creds_dir
                '-v',
                mount_chalice_package,
            ])

        # flags for cloudformation package command
        package_flags = ' '.join([
            '--template-file ./sam.yaml',
            '--s3-bucket',
            bucket,
            '--output-template-file sam-packaged.yaml',
        ])
        # construct package cmd
        cmd_package = 'docker run --rm -it {mount_points} {cmd} {flags}'.format(
            mount_points=mount_points,
            cmd='amazon/aws-cli cloudformation package',
            flags=package_flags,
        )

        # execute package cmd
        logger.info('Uploading foursight package...')
        logger.info(cmd_package)
        os.system(cmd_package)  # results in sam-packaged.yaml being added to args.output_file

        # flags for cloudformation deploy command (change set upload only, no template execution)
        deploy_flags = ' '.join([
            '--template-file ./sam-packaged.yaml',
            '--s3-bucket',
            bucket,
            '--stack-name',
            stack.name.stack_name,
            cls.build_capability_param(stack),  # defaults to IAM
            '--no-execute-changeset',  # creates a changeset, does not execute template
        ])
        # construct deploy cmd
        cmd_deploy = 'docker run --rm -it {mount_points} {cmd} {flags}'.format(
            mount_points=mount_points,
            cmd='amazon/aws-cli cloudformation deploy',
            flags=deploy_flags,
        )

        logger.info('Creating foursight changeset...')
        logger.info(cmd_deploy)
        os.system(cmd_deploy)

    @classmethod
    def upload_cloudformation_template(cls, args, stack, file_path):

        creds_dir = ConfigManager.get_creds_dir()  # was args.creds_dir

        # if cls.is_legacy(args):
        #     network_stack_name, _ = c4_stack_trial_network_metadata()
        #
        #     parameter_flags = [
        #         '--parameter-overrides',  # the flag itself
        #         cls.build_parameter_override(param_name='NetworkStackNameParameter',
        #                                      value=network_stack_name.stack_name),
        #     ]
        #
        #     flags = cls.build_flags(
        #         template_flag=cls.build_template_flag(file_path=file_path),
        #         stack_flag=cls.build_stack_flag(stack_name=stack.name.stack_name),
        #         parameter_flags=' '.join(parameter_flags),
        #         capability_flags=cls.build_capability_param(stack),  # defaults to IAM
        #     )
        # else:
        if True:  # We don't want to consider the legacy case any more. -kmp&will 28-Jul-2021

            network_stack_name, _ = c4_alpha_stack_trial_metadata(name='network')  # XXX: constants
            iam_stack_name, _ = c4_alpha_stack_trial_metadata(name='iam')
            ecr_stack_name, _ = c4_alpha_stack_trial_metadata(name='ecr')
            logging_stack_name, _ = c4_alpha_stack_trial_metadata(name='logging')
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
                    cls.build_parameter_override(param_name='LoggingStackNameParameter',
                                                 value=logging_stack_name.stack_name),
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
            mount_creds=f'{creds_dir}:/root/.aws',  # was args.creds_dir
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
        result = not args.alpha
        if result:
            raise NotImplementedError("We don't implement legacy support any more.")
        return result

    @staticmethod
    def resolve_account(args):
        """ Figures out which account is in use based on the name of the creds dir"""
        ignored(args)
        creds_dir = ConfigManager.get_creds_dir()  # was args.creds_dir
        creds_file = f'{creds_dir}/test_creds.sh'
        account_number = os.environ.get(ACCOUNT_NUMBER)
        account = C4Account(account_number=account_number,
                            # creds_dir=creds_dir,
                            creds_file=creds_file)
        return account

    @staticmethod
    def resolve_alpha_stack(args):
        """ Figures out which stack to run in the ECS case. """
        account = C4Client.resolve_account(args)
        stack_creator = lookup_stack_creator(name=args.stack, kind='alpha', exact=False)
        stack = stack_creator(account=account)
        return stack

    @staticmethod
    def resolve_legacy_stack(args):
        account = C4Client.resolve_account(args)
        stack_creator = lookup_stack_creator(name=args.stack, kind='legacy', exact=True)
        stack = stack_creator(account=account)
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
                cls.validate_cloudformation_template(file_path=file_path  # , creds_dir=args.creds_dir
                                                     )
            return file_path

    @staticmethod
    def view_changes(args):
        # TODO implement me
        if args.view_changes:
            # fetch current template from cloudformation, convert to json
            # generate current template as json
            # view and print diffs
            logger.info('I do nothing right now!')  # dcic_utils.diff_utils.

    # @classmethod
    # @contextmanager
    # def validate_and_source_configuration(cls, *, creds_dir):
    #     """ Validates that required keys are in config.json and overrides the environ for the
    #         invocation of the infra build. Yields control once the environment has been
    #         adjusted, transferring back to the caller - see provision_stack.
    #     """
    #     with ConfigManager.validate_and_source_configuration(creds_dir=creds_dir
    #             # , config_file=cls.CONFIGURATION
    #                                                          ):
    #         yield

        # if not os.path.exists(cls.CONFIGURATION):
        #     raise CLIException('Required configuration file not present! Write config.json')
        # config = cls.load_config(cls.CONFIGURATION)
        # if 'S3_ENCRYPT_KEY' not in config:
        #     s3_key_file = os.path.join(creds_dir, "s3_encrypt_key.txt")
        #     s3_encrypt_key = file_contents(s3_key_file).strip('\n')
        #     config[S3_ENCRYPT_KEY] = s3_encrypt_key
        # for required_key in [DEPLOYING_IAM_USER, ENV_NAME, S3_ENCRYPT_KEY]:
        #     if required_key not in config:
        #         raise CLIException('Required key in configuration file not present: %s' % required_key)
        # with override_environ(**config):
        #     yield

    # @classmethod
    # def load_config(cls, filename):
    #     """
    #     Loads a .json file, casting all the resulting dictionary values to strings
    #     so they are suitable config file values.
    #     """
    #     with open(filename) as fp:
    #         config = json.load(fp)
    #         config = {k: str(v) for k, v in config.items()}
    #         return config

    @classmethod
    def provision_stack(cls, args):
        """ Implements 'provision' command. """

        creds_dir = ConfigManager.get_creds_dir()  # was args.creds_dir

        with ConfigManager.validate_and_source_configuration(creds_dir=creds_dir):
            # if cls.is_legacy(args):
            #     stack = cls.resolve_legacy_stack(args)
            # else:
            if True:  # We're not considering the legacy case any more. -kmp&will 28-Jul-2021
                stack = cls.resolve_alpha_stack(args)

            # Handle foursight
            if 'foursight' in args.stack:  # specific case for foursight template build + upload
                stack.package(args)
                if args.upload_change_set:
                    cls.upload_chalice_package(args, stack)
            # Handle 4dn-cloud-infra stacks
            else:
                file_path = cls.write_and_validate_template(args, stack)  # could exit if stdout arg is provided
                cls.view_changes(args)  # does nothing as of right now
                if args.upload_change_set:
                    cls.upload_cloudformation_template(args, stack, file_path)  # if desired

    @classmethod
    def manage_tibanna(cls, args):
        """ Implements 'tibanna' command. """
        # We want to install tibanna differently. -kmp&will 28-Jul-2021
        raise NotImplementedError("c4_stack_trial_tibanna is not implemented (in manage_tibanna).")
        # account = C4Client.resolve_account(args)
        # c4_tibanna = c4_stack_trial_tibanna(account=account)
        # c4_tibanna_part = c4_tibanna.parts[0]  # better way to reference tibanna part
        # if args.confirm:
        #     dry_run = False
        # else:
        #     dry_run = True
        # if args.init_tibanna:  # runs initial tibanna setup
        #     c4_tibanna_part.initial_deploy(dry_run=dry_run)
        # elif args.tibanna_run:  # runs a workflow on tibanna
        #     logger.warning(f'tibanna run on {args.tibanna_run}')
        #     c4_tibanna_part.tibanna_run(input=args.tibanna_run, dry_run=dry_run)
        # elif args.cmd == [] or args.cmd[0] == 'help':  # displays tibanna help
        #     c4_tibanna_part.run_tibanna_cmd(['--help'])
        # else:  # runs given tibanna command directly
        #     c4_tibanna_part.run_tibanna_cmd(args.cmd, dry_run=dry_run)

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


# AWS_DEFAULT_TEST_CREDS_DIR_FILE = "~/.aws_test_creds_dir"
# AWS_DEFAULT_DEFAULT_TEST_CREDS_DIR = "~/.aws_test"
#
#
# def aws_default_test_creds_dir():
#     # For anyone who doesn't want to use ~/.aws_test, you can put the dir you want in ~/.aws_test_creds_dir
#     # However, you might also want to see the use_test_creds command in the c4-scripts repository. -kmp 8-Jul-2021
#     file = os.path.expanduser(AWS_DEFAULT_TEST_CREDS_DIR_FILE)
#     if os.path.exists(file):
#         creds_dir = os.path.expanduser(file_contents(file).strip())
#         if isinstance(creds_dir, str) and os.path.exists(creds_dir) and os.path.isdir(creds_dir):
#             return creds_dir
#     return os.path.expanduser(AWS_DEFAULT_DEFAULT_TEST_CREDS_DIR)


def cli():
    """Set up and run the 4dn cloud infra command line scripts"""
    parser = argparse.ArgumentParser(description='4DN Cloud Infrastructure')
    parser.add_argument('--debug', action='store_true', help='Sets log level to debug')
    parser.add_argument('--creds_dir', default=ConfigManager.compute_aws_default_test_creds_dir(),
                        help='Sets aws creds dir', type=str)
    subparsers = parser.add_subparsers(help='Commands', dest='command')

    # Configure 'provision' command
    # TODO flag for log level
    parser_provision = subparsers.add_parser('provision', help='Provisions cloud resources for CGAP/4DN')
    parser_provision.add_argument('stack', help='Select stack to operate on: {}'.format(C4Client.SUPPORTED_STACKS))
    parser_provision.add_argument('--alpha', action='store_true', help='Triggers building of the Alpha (ECS) stack',
                                  default=False)
    parser_provision.add_argument('--stdout', action='store_true', help='Writes template to STDOUT only')
    parser_provision.add_argument('--validate', action='store_true', help='Verifies template')
    parser_provision.add_argument('--view_changes', action='store_true', help='TBD: view changes made to template')
    parser_provision.add_argument('--stage', type=str, choices=['dev', 'prod'],
                                  help="package stage. Must be one of 'prod' or 'dev' (foursight only)")
    parser_provision.add_argument('--merge_template', type=str,
                                  help='Location of a YAML template to be merged into the generated template \
                                  (foursight only)')
    parser_provision.add_argument('--output_file', type=str,
                                  help='Location of a directory for output cloudformation (foursight only)')
    parser_provision.add_argument('--trial', action='store_true',
                                  help='Use TRIAL creds when building the config (foursight only; experimental)')
    parser_provision.add_argument('--upload_change_set', action='store_true',
                                  help='Uploads template and provisions change set')
    parser_provision.set_defaults(func=C4Client.provision_stack)

    # TODO command for Cloud Formation deploy flow: execute_change_set

    # Configure 'tibanna' command, for managing a tibanna installation on cloud infrastructure
    parser_tibanna = subparsers.add_parser('tibanna', help='Helps manage and provision tibanna for CGAP/4DN')
    parser_tibanna.add_argument('cmd', type=str, nargs='*',
                                help='Runs the tibanna command-line for the trial account')
    parser_tibanna.add_argument('--init_tibanna', action='store_true',
                                help='Initializes tibanna group with private buckets. Requires c4-tibanna-trial.')
    parser_tibanna.add_argument('--tibanna_run', nargs='?', default=None,
                                const='tibanna_inputs/trial_tibanna_test_input.json',
                                help='Runs a sample tibanna input using private buckets. Requires c4-tibanna-trial.')
    parser_tibanna.add_argument('--confirm', action='store_true',
                                help='Confirms this command will run in the configured account. Defaults to false.')
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
    ConfigManager.set_creds_dir(args.creds_dir)  # This must be done as early as possible for good consistency.

    if not args.alpha:
        raise NotImplementedError("We don't implement the non --alpha case any more.")

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
