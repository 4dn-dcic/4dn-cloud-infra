import argparse
import io
import logging
import os
import shutil
import tempfile
# import json

# from contextlib import contextmanager
from dcicutils.misc_utils import ignored, PRINT  # , file_contents, override_environ
from .constants import Settings
from .info.aws_util import AWSUtil
from .base import lookup_stack_creator, ConfigManager
from .exceptions import CLIException
from .part import C4Account
from .stack import BaseC4FoursightStack  # , C4FoursightCGAPStack
# from .stacks.trial import c4_stack_trial_network_metadata, c4_stack_trial_tibanna
from .stacks.alpha_stacks import c4_alpha_stack_metadata

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# TODO constants
SUPPORTED_ECS_STACKS = ['c4-ecs-network-trial', 'c4-ecs-datastore-trial', 'c4-ecs-cluster-trial']
AWS_REGION = 'us-east-1'


class C4Client:
    """ Client class for interacting with and provisioning CGAP Infrastructure as Code. """
    ALPHA_LEAF_STACKS = ['iam', 'logging', 'network', 'appconfig']  # stacks that only export values
    CAPABILITY_IAM = 'CAPABILITY_IAM'
    FOURFRONT_NETWORK_STACK = 'c4-network-main-stack'  # this stack name is shared by all fourfront envs
    # these stacks require CAPABILITY_IAM, just IAM for now
    REQUIRES_CAPABILITY_IAM = ['iam', 'foursight', 'foursight-development', 'foursight-production', 'codebuild',
                               'foursight-smaht']

    @classmethod
    def _out_templates_mapping_for_mount(cls) -> str:
        templates_dir = ConfigManager.templates_dir()
        docker_templates_dir = ConfigManager.templates_dir(relative_to='/root')
        import pdb ; pdb.set_trace()
        mount_yaml = f"{templates_dir}:{docker_templates_dir}"
        return mount_yaml

    @classmethod
    def validate_cloudformation_template(cls, file_path):
        """ Validates CloudFormation template at file_path """
        creds_dir = ConfigManager.get_aws_creds_dir()
        mount_yaml = cls._out_templates_mapping_for_mount()
        mount_creds = f'{creds_dir}:/root/.aws'
        validation_cmd = 'amazon/aws-cli cloudformation validate-template'
        validation_args = f'--template-body file://{file_path}'
        import pdb ; pdb.set_trace()
        docker_invocation = f'docker run --rm -it -v {mount_yaml} -v {mount_creds} {validation_cmd} {validation_args}'
        logger.info('Validating provisioned template...')
        os.system(docker_invocation)

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

    @classmethod
    def upload_chalice_package(cls, *, output_file, stack: BaseC4FoursightStack, bucket=None):
        """ Specific upload process for a chalice application, e.g. foursight. Assumes chalice package has been run.
            How this works:
            1. Mounts the output_file directory to the docker image's execution directory (/root/aws)
            2. Runs aws cloudformation package, which uploads the deploy artifact to the s3 bucket
            3. This command generates a cloudformation template, which is saved to the local deploy artifact directory
            4. Runs aws cloudformation deploy, which generates a changeset based on this generated cloudformation.
        """

        # TODO: this bucketname should come from config.json or some os.environ ...
        if bucket is None:
            bucket = ConfigManager.resolve_bucket_name(ConfigManager.FSBucketTemplate.APPLICATION_VERSIONS)

        creds_dir = ConfigManager.get_aws_creds_dir()
        s3_key = ConfigManager.get_config_setting(Settings.S3_ENCRYPT_KEY_ID, default=None)

        # Mounts the output_file directory to the docker image's execution directory (/root/aws)
        mount_chalice_package = '{}/{}:/aws'.format(os.path.abspath(os.getcwd()), output_file)
        # Creates mount point flags for creds and the chalice package
        mount_points = ' '.join([
                '-v',
                f'{creds_dir}:/root/.aws',
                '-v',
                mount_chalice_package,
            ])

        # flags for cloudformation package command
        import pdb ; pdb.set_trace()
        package_flags = ' '.join([
            '--template-file ./sam.yaml',
            '--s3-bucket',
            bucket,
            '--output-template-file sam-packaged.yaml',

        ])
        if s3_key:  # if an s3 key is set, pass to enable server side encryption
            package_flags += f' --kms-key-id {s3_key}'
        # construct package cmd
        import pdb ; pdb.set_trace()
        cmd_package = 'docker run --rm -it {mount_points} {cmd} {flags}'.format(
            mount_points=mount_points,
            cmd='amazon/aws-cli cloudformation package',
            flags=package_flags,
        )

        # execute package cmd
        logger.info('Uploading foursight package...')
        logger.info(cmd_package)
        os.system(cmd_package)  # results in sam-packaged.yaml being added to output_file

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
        if s3_key:  # if an s3 key is set, pass to enable server side encryption
            deploy_flags += f' --kms-key-id {s3_key}'
        # construct deploy cmd
        import pdb ; pdb.set_trace()
        cmd_deploy = 'docker run --rm -it {mount_points} {cmd} {flags}'.format(
            mount_points=mount_points,
            cmd='amazon/aws-cli cloudformation deploy',
            flags=deploy_flags,
        )

        logger.info('Creating foursight changeset...')
        logger.info(cmd_deploy)
        os.system(cmd_deploy)

    @classmethod
    def upload_cloudformation_template(cls, *, stack, file_path):

        creds_dir = ConfigManager.get_aws_creds_dir()

        # NOTE: We don't want to consider the legacy case any more. -kmp&will 28-Jul-2021

        network_stack_name, _ = c4_alpha_stack_metadata(name='network')  # XXX: constants
        iam_stack_name, _ = c4_alpha_stack_metadata(name='iam')
        ecr_stack_name, _ = c4_alpha_stack_metadata(name='ecr')
        logging_stack_name, _ = c4_alpha_stack_metadata(name='logging')
        # TODO incorporate datastore output to ECS stack
        datastore_stack_name, _ = c4_alpha_stack_metadata(name='datastore')

        # if we are building a leaf stack, our upload doesn't require these parameter overrides
        # since we are not importing values from other stacks
        if stack.name.stack_name in cls.ALPHA_LEAF_STACKS:
            parameter_flags = ''
        else:
            parameter_flags = [
                '--parameter-overrides',  # the flag itself
                cls.build_parameter_override(param_name='NetworkStackNameParameter',
                                             value=ConfigManager.app_case(if_cgap=network_stack_name.stack_name,
                                                                          if_ff=cls.FOURFRONT_NETWORK_STACK,
                                                                          if_smaht=network_stack_name.stack_name)),
                cls.build_parameter_override(param_name='ECRStackNameParameter',
                                             value=ecr_stack_name.stack_name),
                cls.build_parameter_override(param_name='IAMStackNameParameter',
                                             value=iam_stack_name.stack_name),
                cls.build_parameter_override(param_name='LoggingStackNameParameter',
                                             value=logging_stack_name.stack_name),
                # TODO: integrate so auto-populates into GAC
                # cls.build_parameter_override(param_name='DatastoreStackNameParameter',
                #                              value=datastore_stack_name.stack_name)
            ]
        flags = cls.build_flags(
            template_flag=cls.build_template_flag(file_path=file_path),
            stack_flag=cls.build_stack_flag(stack_name=stack.name.stack_name),
            parameter_flags=' '.join(parameter_flags),
            capability_flags=cls.build_capability_param(stack)  # defaults to IAM
        )

        import pdb ; pdb.set_trace()
        cmd = 'docker run --rm -it -v {mount_yaml} -v {mount_creds} {command} {flags}'.format(
            mount_yaml=cls._out_templates_mapping_for_mount(),
            mount_creds=f'{creds_dir}:/root/.aws',
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
    def resolve_account():
        """ Figures out which account is in use. """  # Used to be based on the name of the creds dir. Not any more.
        creds_dir = ConfigManager.get_aws_creds_dir()
        creds_file = f'{creds_dir}/test_creds.sh'  # TODO: Consider renaming to remove 'test_' from the name.
        account_number = ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER)
        account = C4Account(account_number=account_number, creds_file=creds_file)
        return account

    @staticmethod
    def resolve_alpha_stack(stack_name):
        """ Figures out which stack to run in the ECS case. """
        try:
            account = C4Client.resolve_account()
            stack_creator = lookup_stack_creator(name=stack_name, kind='alpha', exact=True)
            stack = stack_creator(account=account)
            return stack
        except CLIException as e:
            PRINT(f'Got known exception {e}')
            return None

    @staticmethod
    def resolve_4dn_stack(stack_name):
        """ Figures out which stack to run for 4dn specific stacks. """
        try:
            account = C4Client.resolve_account()
            stack_creator = lookup_stack_creator(name=stack_name, kind='4dn', exact=True)
            stack = stack_creator(account=account)
            return stack
        except CLIException as e:
            PRINT(f'Got known exception {e}')
            return None

    @classmethod
    def write_and_validate_template(cls, stack, use_stdout_and_exit, validate):
        """ Writes and validates the generated cloudformation template
            Note that stdout does not validate, making it not very useful.
        """
        if use_stdout_and_exit:
            stack.print_template(stdout=True)
            exit(0)  # if this is specified, we definitely don't want to upload
        else:
            template_object, template_name = stack.print_template()
            # path = ConfigManager.RELATIVE_TEMPLATES_DIR + "/"
            # file_path = ''.join(['/root/', path, template_name])
            file_path = os.path.join(ConfigManager.templates_dir(relative_to='/root'), template_name)
            logger.info('Written template to {}'.format(file_path))
            if validate:
                cls.validate_cloudformation_template(file_path=file_path)
            return file_path

    @classmethod
    def view_changes(cls, stack, file_path):
        ignored(stack, file_path)  # we probably need to use these when we implement this.
        # TODO: Implement this.
        #       1. Fetch current template from cloudformation.
        #       2. Convert template to json.
        #       3. Generate current template as json.
        #       4. view and print diffs using dcic_utils.diff_utils.
        logger.info('I do nothing right now!')

    @classmethod
    def is_foursight_stack(cls, stack):
        return isinstance(stack, BaseC4FoursightStack)

    @classmethod
    def provision_stack(cls, args):
        """ Implements 'provision' command. """

        stack_name = args.stack
        upload_change_set = args.upload_change_set
        output_file = args.output_file
        use_stdout_and_exit = args.stdout
        validate = args.validate
        view_changes = args.view_changes

        with ConfigManager.validate_and_source_configuration():

            PRINT("Account=", ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER))
            PRINT("AWS_ACCESS_KEY_ID=", os.environ.get("AWS_ACCESS_KEY_ID"))

            alpha_stack = cls.resolve_alpha_stack(stack_name=stack_name)
            dcic_stack = cls.resolve_4dn_stack(stack_name=stack_name)
            if alpha_stack and dcic_stack:
                raise CLIException(f'Ambiguous stack name {stack_name} resolved'
                                   f' to both alpha and 4dn stacks! Update your stack'
                                   f' name so it does not clash with other stacks.')
            stack = None
            if alpha_stack:
                stack = alpha_stack
            if dcic_stack:
                stack = dcic_stack
            if not stack:
                raise CLIException(f'Did not locate stack name: {stack_name}')

            if cls.is_foursight_stack(stack):  # Handle foursight

                # A foursight template build + upload is done differently than other stacks.

                if not use_stdout_and_exit and not output_file:
                    # If arguments not supplied in this case, we do some useful defaulting.
                    output_file = f"out/foursight-{args.stage}-tmp/"
                    args.output_file = output_file
                    PRINT(f"Using default output location: {output_file}")
                elif use_stdout_and_exit:
                    output_file = tempfile.NamedTemporaryFile().name
                    args.output_file = output_file

                stack.package_foursight_stack(args)  # <-- this will implicitly use args.stage, among others
                if upload_change_set:
                    import pdb ; pdb.set_trace()
                    bucket = ConfigManager.get_config_setting(Settings.FOURSIGHT_APP_VERSION_BUCKET, default=None)
                    cls.upload_chalice_package(output_file=output_file, stack=stack, bucket=bucket)
                if use_stdout_and_exit:
                    with io.open(os.path.join(output_file, "sam.yaml"), "r") as output_file_fp:
                        for line in output_file_fp.readlines():
                            print(line, end='')
                    shutil.rmtree(output_file)
            else:
                # Handle 4dn-cloud-infra stacks
                file_path = cls.write_and_validate_template(stack=stack,
                                                            # NOTE: This function will exit without continuing
                                                            #       if a '--stdout' arg was provided.
                                                            use_stdout_and_exit=use_stdout_and_exit,
                                                            validate=validate)
                if view_changes:
                    # NOTE: This is a stub that does nothing for now. -kmp 5-Aug-2021
                    cls.view_changes(stack=stack, file_path=file_path)
                if upload_change_set:
                    # If requested with '--upload-change-set', upload to CloudFormation...
                    cls.upload_cloudformation_template(stack=stack, file_path=file_path)

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

        upload = args.upload
        versioned = args.versioned
        s3 = args.s3

        aws_util = AWSUtil()
        if upload and versioned:
            # TODO add GSheet functionality as a src util
            logger.info('Use ./scripts/upload_vspreadsheets to upload versioned s3 spreadsheets')
        if versioned:
            logger.info('Generating versioned s3 buckets summary tsv...')
            aws_util.generate_versioned_files_summary_tsvs()
        if s3:
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
    parser_provision.add_argument('stack', help='Select stack to build')
    parser_provision.add_argument('--alpha', dest='warn_alpha_arg_deprecated', action='store_true',
                                  help="This argument is deprecated because 'alpha' is the default."
                                       " You can suppress it with --no-alpha.")
    parser_provision.add_argument('--no-alpha', '--legacy',
                                  dest='alpha',
                                  action='store_false',
                                  help='Triggers building of the Alpha (ECS) stack',
                                  default=True)
    parser_provision.add_argument('--stdout', action='store_true', help='Writes template to STDOUT only')
    parser_provision.add_argument('--validate', action='store_true', help='Verifies template')
    parser_provision.add_argument('--view-changes',
                                  '--view_changes',  # for compatibility
                                  dest="view_changes",
                                  action='store_true', help='TBD: view changes made to template')
    parser_provision.add_argument('--stage', type=str, choices=['dev', 'prod'],
                                  help="package stage. Must be one of 'prod' or 'dev' (foursight only)",
                                  default='prod')
    parser_provision.add_argument('--merge-template',
                                  '--merge_template',  # for compatibility
                                  dest="merge_template",
                                  type=str,
                                  help='Location of a YAML template to be merged into the generated template \
                                  (foursight only)')
    parser_provision.add_argument("--output-file",
                                  '--output_file',  # for compatibility
                                  dest="output_file",
                                  type=str,
                                  help='Location of a directory for output cloudformation (foursight only)',
                                  )
    parser_provision.add_argument('--trial', dest='warn_trial_arg_deprecated', action='store_true',
                                  help="This argument is deprecated because 'trial' is the default."
                                       " You can suppress it with --no-trial.")
    parser_provision.add_argument('--no-trial', '--production', action='store_false', dest='trial', default=True,
                                  help='Suppress use of TRIAL creds when building the config'
                                       ' (foursight only; experimental)')
    parser_provision.add_argument('--upload-change-set',
                                  '--upload_change_set',  # for compatibility
                                  dest="upload_change_set",
                                  action='store_true',
                                  help='Uploads template and provisions change set')
    # TODO: For this and (any/all) other args, we should probably pass the arg values around explicitly
    # rather than treating the args as a sort of global bucket anyone can pick anything from anywhere.
    parser_provision.add_argument("--foursight-identity", dest="foursight_identity", type=str,
                                  help='IDENTITY value (i.e. GAC name) for Foursight')
    parser_provision.set_defaults(func=C4Client.provision_stack)

    # TODO command for Cloud Formation deploy flow: execute_change_set

    # Configure 'tibanna' command, for managing a tibanna installation on cloud infrastructure
    parser_tibanna = subparsers.add_parser('tibanna', help='Helps manage and provision tibanna for CGAP/4DN')
    parser_tibanna.add_argument('cmd', type=str, nargs='*',
                                help='Runs the tibanna command-line for the trial account')
    parser_tibanna.add_argument("--init-tibanna",
                                '--init_tibanna',  # for compatibility
                                dest="init_tibanna",
                                action='store_true',
                                help='Initializes tibanna group with private buckets. Requires c4-tibanna-trial.')
    parser_tibanna.add_argument('--tibanna-run',
                                '--tibanna_run',  # for compatibility
                                dest="tibanna_run",
                                nargs='?', default=None,
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

    if not args.alpha:
        raise NotImplementedError("We don't implement the --no-alpha (or --legacy) case any more.")
    elif args.warn_alpha_arg_deprecated:
        PRINT("The --alpha argument is deprecated, since it is now the default.")

    if not args.trial:
        raise NotImplementedError("We don't support the --no-trial (or --production) case right now.")
    elif args.warn_trial_arg_deprecated:
        PRINT("The --trial argument is deprecated, since it is now the default.")

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
