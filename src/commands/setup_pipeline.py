import argparse
import contextlib
# import io
import os
# import re
import subprocess

from dcicutils.misc_utils import ignorable, PRINT
from dcicutils.command_utils import yes_or_no
from ..base import ConfigManager, Settings, ini_file_get
from .find_resources import DatastoreAttributeCommand


_MY_DIR = os.path.dirname(__file__)

_ROOT_DIR = os.path.dirname(os.path.dirname(_MY_DIR))  # We're in <root>/src/commands, so go up two levels

ALL_SUB_REPOS_DIR_FILENAME = "repositories"
ALL_SUB_REPOS_PATH = os.path.join(_ROOT_DIR, ALL_SUB_REPOS_DIR_FILENAME)

PIPELINE_REPO = "https://github.com/dbmi-bgm/cgap-pipeline.git"
PIPELINE_DIR_FILENAME = "cgap-pipeline"
PIPELINE_PATH = os.path.join(ALL_SUB_REPOS_PATH, PIPELINE_DIR_FILENAME)


class ShellScript:

    EXECUTABLE = "/bin/bash"

    def __init__(self, working_dir=None, executable=None, simulate=False):
        self.executable = executable or self.EXECUTABLE
        self.working_dir = working_dir
        self.simulate = simulate
        self.script = ""

    def execute(self, command):
        """This isn't really executing the command, just building it into the script."""
        if self.script:
            self.script = f"{self.script}; {command}"
        else:
            self.script = command

    def finalize(self):
        """This is where it's really executed."""
        if self.simulate:
            PRINT("SIMULATED:")
            PRINT("=" * 80)
            PRINT(self.script.replace('; ', ';\\\n '))
            PRINT("=" * 80)
        elif self.script:
            subprocess.run(self.script, shell=True, executable=self.executable)


@contextlib.contextmanager
def shell_script(working_dir=None, executable=None, simulate=False):
    script = ShellScript(working_dir=working_dir, executable=executable, simulate=simulate)
    if working_dir:
        script.execute(f'pushd {working_dir} > /dev/null')
        script.execute(f'echo "Selected working directory $(pwd)."')
    yield script
    if working_dir:
        script.execute(f'popd > /dev/null')
        script.execute(f'echo "Restored working directory $(pwd)."')
    script.finalize()


def setup_pipeline(simulate=False, no_query=False):

    ignorable(no_query)

    if not os.path.exists(ALL_SUB_REPOS_PATH):
        print(f"Creating {ALL_SUB_REPOS_PATH}...")
        os.mkdir(ALL_SUB_REPOS_PATH)

    if not os.path.exists(PIPELINE_PATH):
        with shell_script(working_dir=ALL_SUB_REPOS_PATH, simulate=simulate) as script:
            script.execute(f'echo "Cloning {PIPELINE_REPO}..."')
            script.execute(f'git clone {PIPELINE_REPO} {PIPELINE_DIR_FILENAME}')
            script.execute(f'echo "Done cloning {PIPELINE_REPO}."')
    else:

        with shell_script(working_dir=PIPELINE_PATH, simulate=simulate) as script:
            script.execute(f'echo "Pulling latest changes for {PIPELINE_REPO}..."')
            script.execute(f'git pull')
            script.execute(f'echo "Done pulling latest changes for {PIPELINE_REPO}."')


CGAP_REFERENCE_FILE_REGISTRY_URL = "s3://cgap-reference-file-registry"


def setup_reference_files(simulate=False, no_query=False):

    with shell_script(simulate=simulate) as script:

        account_number = ConfigManager.get_config_setting(Settings.ACCOUNT_NUMBER, default=None)
        aws_access_key_id = ini_file_get("custom/aws_creds/credentials", "aws_access_key_id")

        cgap_repo_app_files_bucket = DatastoreAttributeCommand.find_attributes('AppFilesBucket')
        cgap_repo_files_bucket_url = f"s3://{cgap_repo_app_files_bucket}"

        def check_script_consistency(*, script, env_var, value):
            fail = f"The value of environment variable {env_var}, '${env_var}', is not {value}."
            succeed = f"Verified that {env_var} = '...{value[-4:]}'"
            script.execute(f'if [ "${env_var}" != "{value}" ]; then echo "{fail}"; exit 1;'
                           f' else echo "{succeed}"; fi')

        check_script_consistency(script=script, env_var='ACCOUNT_NUMBER', value=account_number)
        check_script_consistency(script=script, env_var='AWS_ACCESS_KEY_ID', value=aws_access_key_id)

        PRINT(f"Preparing to copy reference files from the public CGAP reference file registry.")
        PRINT(f"* This will copy from: {CGAP_REFERENCE_FILE_REGISTRY_URL}")
        PRINT(f"* This will copy to:   {cgap_repo_files_bucket_url}")
        PRINT(f"* A full copy takes 45-60 minutes.")
        PRINT(f"* If resuming or refreshing after a prior attempt, time required is proportional to remaining work.")

        if no_query or yes_or_no(f"Do you want to copy these files?"):

            script.execute(f"{_ROOT_DIR}/scripts/assure-awscli")
            script.execute(f'echo "Starting copying at $(date)."')
            sync_command = f"aws s3 sync {CGAP_REFERENCE_FILE_REGISTRY_URL} {cgap_repo_files_bucket_url}"
            script.execute(sync_command)
            script.execute(f'echo "Done copying at $(date)."')




def gather_setup_args(override_args=None):
    parser = argparse.ArgumentParser(description='Assures presence and initialization of the global env bucket.')
    parser.add_argument('--env_name', help='The environment name to assure', default=None, type=str)
    parser.add_argument('--simulate', default=False, action="store_true", help="Whether to just simulate action.")
    parser.add_argument('--no-query', default=False, action="store_true", help="Whether to suppress querying.")
    args = parser.parse_args(args=override_args)
    return args

def main(override_args=None):
    ""
    args = gather_setup_args(override_args=override_args)
    with ConfigManager.validate_and_source_configuration():
        setup_pipeline(simulate=args.simulate, no_query=args.no_query)
        setup_reference_files(simulate=args.simulate, no_query=args.no_query)


if __name__ == '__main__':
    main()
