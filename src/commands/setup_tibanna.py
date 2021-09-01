import argparse
import contextlib
import glob
import os

from botocore.client import ClientError
from dcicutils.command_utils import yes_or_no, shell_script, module_warnings_as_ordinary_output, ShellScript
from dcicutils.lang_utils import there_are
from dcicutils.misc_utils import ignored, PRINT
from dcicutils.s3_utils import s3Utils
from typing import Optional
from ..base import (
    ConfigManager,  # Settings, ini_file_get,
    ENV_NAME, configured_main_command, check_environment_variable_consistency,
)
from ..parts.datastore import C4DatastoreExports
from .find_resources import DatastoreAttributeCommand, get_health_page_url, is_portal_uninitialized


# ================================================================================

# General support for command operations that follow

def bucket_head(*, bucket_name, s3=None):  # TODO: Move to dcicutils.cloudformation_utils ?
    try:
        s3 = s3 or s3Utils().s3
        info = s3.head_bucket(Bucket=bucket_name)
        return info
    except ClientError:
        return None


def bucket_exists(*, bucket_name, s3=None):  # TODO: Move to dcicutils.cloudformation_utils?
    return bool(bucket_head(bucket_name=bucket_name, s3=s3))


# ================================================================================


def assure_venv(script, default_venv_name='cgpipe_env'):
    venv_names = glob.glob(os.path.join(PIPELINE_PATH, "*env"))
    n_venv_names = len(venv_names)
    if n_venv_names == 0:
        venv_name = default_venv_name
        script.do(f'echo "Creating virtual environment {venv_name}."')
        script.do(f'pyenv exec python -m venv {venv_name} || python3 -m venv {venv_name}')
        script.do(f'source {venv_name}/bin/activate')
        script.do(f'echo "Using setup.py to install requirements for virtual environment {venv_name}."')
        script.do(f'echo "The installation process for {venv_name} may take about 3-5 minutes. Please be patient."')
        script.do(f'echo "Starting installation of {venv_name} requirements at $(date)."')
        script.do(f'python setup.py develop')
        script.do(f'echo "Finished installation of {venv_name} requirements at $(date)."')
    elif n_venv_names == 1:
        [venv_name] = venv_names
        script.do(f'echo "Activating existing virtual environment {venv_name}."')
        script.do(f'source {venv_name}/bin/activate')
    else:
        raise RuntimeError(there_are(venv_names, kind="virtual environment"))


# TODO: The ExtendedShellScript class should be merged into dcicutils.command_utils.ShellScript sometime,
#   but anticipating I might need to do some more experimentation, I made the shell_script context manager
#   take a shell script class as an argument so I could make these changes locally for now. This solves
#   the problem that a series of .do_first() commands will execute backward, as each goes before the previous.
#   So instead if you do:
#      with script.done_first() as front_part:
#         front_part.do()
#         front_part.do()
#   you can get a series of commands done in normal order appended to one another and then prepended
#   to the main script.
#   -kmp 30-Aug-2021

class ExtendedShellScript(ShellScript):

    def __init__(self, executable: Optional[str] = None, simulate=False, no_execute=False, **script_options):
        self.no_execute = no_execute
        super().__init__(executable=executable, simulate=simulate, **script_options)  # noQA

    def execute(self, **pipe_args):
        if not self.no_execute:
            super().execute(**pipe_args)  # noQA

    @contextlib.contextmanager
    def done_first(self):
        with shell_script(script_class=self.__class__, no_execute=True) as script_segment:
            yield script_segment
            self.do_first(script_segment.script)


@contextlib.contextmanager
def cloud_infra_shell_script(working_dir=None, executable=None, simulate=False):
    with shell_script(working_dir=working_dir, executable=executable, simulate=simulate,
                      script_class=ExtendedShellScript) as script:
        check_script_environment_consistency(script)
        yield script


def check_script_environment_consistency(script, verbose_success=False):

    assert isinstance(script, ExtendedShellScript)
    with script.done_first() as first_part_of_script:

        def script_checker(*, env_var, failure_message, success_message, expected_value=None, expected_hash=None):
            if expected_hash:
                if expected_value:
                    raise ValueError("Exactly one of expected_value or expected_hash is required.")
                first_part_of_script.do(f'if [ $(md5 -q -s "${env_var}") != "{expected_hash}" ];'
                                        f' then echo "{failure_message} (in script)"; exit 1;'
                                        f' else echo "{success_message} (in script)"; fi')
            elif expected_value:
                first_part_of_script.do(f'if [ "${env_var}" != "{expected_value}" ];'
                                        f' then echo "{failure_message} (in script)"; exit 1;'
                                        f' else echo "{success_message} (in script)"; fi')
            else:
                raise ValueError("Exactly one of expected_value or expected_hash is required.")

        check_environment_variable_consistency(checker=script_checker, verbose_success=verbose_success)


# ================================================================================


def setup_tibanna_precheck(*, env_name):

    # Find out what tibanna output bucket is intended.
    intended_tibanna_output_bucket = C4DatastoreExports.get_tibanna_output_bucket()

    if not os.environ.get('GLOBAL_ENV_BUCKET') and not os.environ.get('GLOBAL_BUCKET_ENV'):
        # This is a particularly bad error becuse we could end up writing to the wrong buckets if not careful.
        # Here we don't take any chances with True/False return values.
        raise RuntimeError("One of GLOBAL_ENV_BUCKET or GLOBAL_BUCKET_ENV (preferably the former)"
                           " must be set for this to work.")

    # Verify that a tibanna output bucket (possibly named ...-tibanna-logs or ...-tibanna-output) is set up at all.
    # This process will assure that the CGAP health page is reporting its name. That's where s3Utils gets the info.

    with module_warnings_as_ordinary_output('dcicutils.s3_utils'):  # This will remove the scary "WARNING" part.
        s3u = s3Utils(env=env_name)

    tibanna_output_bucket = s3u.tibanna_output_bucket

    if tibanna_output_bucket != intended_tibanna_output_bucket:
        PRINT(f"We expected the tibanna output bucket would be {intended_tibanna_output_bucket}.")
        PRINT(f"However, s3Utils().tibanna_output_bucket is returning {tibanna_output_bucket}.")
        return False

    if tibanna_output_bucket:
        PRINT(f"The S3 tibanna output bucket, {s3u.tibanna_output_bucket}, has been correctly set up.")
    else:

        PRINT(f"Unable to determine the name of the Tibanna output bucket to use.")
        PRINT("The class dcicutils.s3_utils.S3Utils is used to find this information.")
        PRINT("This would normally come from the portal health page.")

        try:
            health_page_url = get_health_page_url(env_name=env_name)
            try:
                if is_portal_uninitialized(sample_url=health_page_url):
                    return  # an error message was already shown
            except Exception:
                PRINT(f"Failing to get information from the health page URL, {health_page_url}.")
                return False

        except Exception:
            PRINT(f"This is probably because we are also unable to compute the name of the health page.")
            return False

        PRINT(f"The health page is: {health_page_url}")
        PRINT(f"You can use the command 'show-health-page-url' to be reminded of that URL.")
        PRINT(f"You can use the command 'open-health-page-url' to visit that page to make sure it's working properly.")
        PRINT(f"That page is expected to have a key named {s3Utils.TIBANNA_OUTPUT_BUCKET_HEALTH_PAGE_KEY}.")
        return False

    if bucket_exists(bucket_name=tibanna_output_bucket, s3=s3u.s3):
        PRINT(f"The S3 tibanna output bucket, {tibanna_output_bucket}, exists on S3.")
    else:
        PRINT(f"The S3 tibanna output bucket, {tibanna_output_bucket}, does NOT exist on S3.")
        PRINT(f"Either your GLOBAL_ENV_BUCKET is set wrong, or you have not provisioned 'datastore'.")
        return False

    return True


_MY_DIR = os.path.dirname(__file__)

_ROOT_DIR = os.path.dirname(os.path.dirname(_MY_DIR))  # We're in <root>/src/commands, so go up two levels

ALL_SUB_REPOS_DIR_FILENAME = "repositories"
ALL_SUB_REPOS_PATH = os.path.join(_ROOT_DIR, ALL_SUB_REPOS_DIR_FILENAME)

PIPELINE_REPO = "https://github.com/dbmi-bgm/cgap-pipeline.git"
PIPELINE_DIR_FILENAME = "cgap-pipeline"
PIPELINE_PATH = os.path.join(ALL_SUB_REPOS_PATH, PIPELINE_DIR_FILENAME)

PIPELINE_VERSION = 'v24'


def setup_pipeline_repo(env_name=ENV_NAME, simulate=False, no_query=False, pipeline_version=PIPELINE_VERSION):

    ignored(env_name, no_query)

    if not os.path.exists(ALL_SUB_REPOS_PATH):
        print(f"Creating {ALL_SUB_REPOS_PATH}...")
        os.mkdir(ALL_SUB_REPOS_PATH)

    if not os.path.exists(PIPELINE_PATH):
        with cloud_infra_shell_script(working_dir=ALL_SUB_REPOS_PATH, simulate=simulate) as script:
            script.do(f'echo "Cloning {PIPELINE_REPO}..."')
            script.do(f'git clone {PIPELINE_REPO} {PIPELINE_DIR_FILENAME}')
            script.pushd(PIPELINE_DIR_FILENAME)
            script.do(f'git checkout {PIPELINE_VERSION}')
            script.popd()
            script.do(f'git checkout {pipeline_version}')
            script.do(f'echo "Done cloning {PIPELINE_REPO}."')
    else:

        with cloud_infra_shell_script(working_dir=PIPELINE_PATH, simulate=simulate) as script:
            script.do(f'echo "Pulling latest changes for {PIPELINE_REPO}..."')
            script.do(f'git checkout {pipeline_version}')
            script.do(f'git pull')
            script.do(f'echo "Done pulling latest changes for {PIPELINE_REPO}."')

    with cloud_infra_shell_script(working_dir=PIPELINE_PATH, simulate=simulate) as script:
        assure_venv(script)


CGAP_REFERENCE_FILE_REGISTRY_URL = "s3://cgap-reference-file-registry"


def setup_reference_files(env_name=ENV_NAME, simulate=False, no_query=False):

    ignored(env_name)

    with cloud_infra_shell_script(simulate=simulate) as script:

        cgap_repo_app_files_bucket = DatastoreAttributeCommand.find_attributes('AppFilesBucket')
        cgap_repo_files_bucket_url = f"s3://{cgap_repo_app_files_bucket}"

        PRINT(f"Preparing to copy reference files from the public CGAP reference file registry.")
        PRINT(f"* This will copy from: {CGAP_REFERENCE_FILE_REGISTRY_URL}")
        PRINT(f"* This will copy to:   {cgap_repo_files_bucket_url}")
        PRINT(f"* A full copy takes 45-60 minutes.")
        PRINT(f"* If resuming or refreshing after a prior attempt, time required is proportional to remaining work.")

        if no_query or yes_or_no(f"Do you want to copy these files?"):

            # We now include this into pyproject.toml
            # script.do(f"{_ROOT_DIR}/scripts/assure-awscli")
            script.do(f'echo "Starting copying at $(date)."')
            sync_command = f"aws s3 sync {CGAP_REFERENCE_FILE_REGISTRY_URL} {cgap_repo_files_bucket_url}"
            script.do(sync_command)
            script.do(f'echo "Finished copying at $(date)."')


def setup_patches(env_name=ENV_NAME, simulate=False, no_query=False):
    ignored(no_query)
    if no_query or yes_or_no("Properly prepared to post patches to portal?"):
        with cloud_infra_shell_script(working_dir=PIPELINE_PATH, simulate=simulate) as script:
            assure_venv(script)
            script.do(f'echo "Starting posting patches at $(date)."')
            script.do(f'python post_patch_to_portal.py --ff-env={env_name} --del-prev-version --ugrp-unrelated')
            script.do(f'echo "Finished posting patches at $(date)."')


# Command setup...

def setup_tibanna_pipeline_repo_main(override_args=None):

    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=ENV_NAME, type=str)
    parser.add_argument('--simulate', default=False, action="store_true", help="Whether to just simulate action.")
    parser.add_argument('--no-query', default=False, action="store_true", help="Whether to suppress querying.")
    parser.add_argument('--pipeline-version', dest="pipeline_version", default=PIPELINE_VERSION,
                        help="Whether to suppress querying.")
    args = parser.parse_args(args=override_args)

    with ConfigManager.validate_and_source_configuration():
        setup_pipeline_repo(
            env_name=args.env_name,
            simulate=args.simulate,
            no_query=args.no_query,
            pipeline_version=args.pipeline_version)


@configured_main_command()
def setup_tibanna_reference_files_main(override_args=None):

    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=ENV_NAME, type=str)
    parser.add_argument('--simulate', default=False, action="store_true", help="Whether to just simulate action.")
    parser.add_argument('--no-query', default=False, action="store_true", help="Whether to suppress querying.")
    args = parser.parse_args(args=override_args)

    setup_reference_files(
        env_name=args.env_name,
        simulate=args.simulate,
        no_query=args.no_query)


@configured_main_command()
def setup_tibanna_patches_main(override_args=None):

    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=ENV_NAME, type=str)
    parser.add_argument('--simulate', default=False, action="store_true", help="Whether to just simulate action.")
    parser.add_argument('--no-query', default=False, action="store_true", help="Whether to suppress querying.")
    args = parser.parse_args(args=override_args)

    setup_patches(
        env_name=args.env_name,
        simulate=args.simulate,
        no_query=args.no_query,
    )


@configured_main_command()
def setup_tibanna_precheck_main(override_args=None):

    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=ENV_NAME, type=str)
    args = parser.parse_args(args=override_args)

    if setup_tibanna_precheck(env_name=args.env_name):
        PRINT("Precheck succeeded.")
    else:
        PRINT("Precheck failed.")


@configured_main_command()
def setup_tibanna_main(override_args=None):
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=ENV_NAME, type=str)
    parser.add_argument('--simulate', default=False, action="store_true", help="Whether to just simulate action.")
    parser.add_argument('--no-query', default=False, action="store_true", help="Whether to suppress querying.")
    parser.add_argument('--pipeline-version', dest="pipeline_version", default=PIPELINE_VERSION,
                        help="Whether to suppress querying.")
    args = parser.parse_args(args=override_args)

    if not setup_tibanna_precheck(env_name=args.env_name):
        exit(1)
    setup_pipeline_repo(
        env_name=args.env_name,
        simulate=args.simulate,
        no_query=args.no_query,
        pipeline_version=args.pipeline_version)
    setup_reference_files(
        env_name=args.env_name,
        simulate=args.simulate,
        no_query=args.no_query)
    setup_patches(
        env_name=args.env_name,
        simulate=args.simulate,
        no_query=args.no_query,
    )
