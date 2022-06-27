import argparse
from dcicutils.misc_utils import PRINT
from dcicutils.ff_utils import get_health_page
from dcicutils.creds_utils import CGAPKeyManager


# Add version identifiers to this constant to get them to show up in
# this command. Note that SPC version is absent since that is populated
# by the UI.
VERSION_ENTRIES = [
    'project_version',
    'python_version',
    'snovault_version',
    'utils_version',
]


def echo_env_status(keyfile_override: str) -> None:
    """ Reads ~/.cgap-keys.json, navigates to the health pages and reports structured
        health information on the various versions.
    """
    PRINT('Echoing environment information from given keyfile - note that valid access keys'
          ' are required!')
    key_manager = CGAPKeyManager(keys_file=keyfile_override)
    keydicts = key_manager.get_keydicts()
    for env_identifier, entries in keydicts.items():
        try:
            health = get_health_page(key=entries)
        except Exception as e:
            PRINT(f'Error acquiring health page for {env_identifier}: {e}')
            continue
        PRINT(f'* {env_identifier} version information:')
        for version_entry in VERSION_ENTRIES:
            PRINT(f'    * {version_entry} --> {health.get(version_entry)}')


def main():
    parser = argparse.ArgumentParser(
        description='Echos version information from ~/.cgap-keys.json or override file.')
    parser.add_argument('--keyfile', help='Pass to override default keyfile', type=str)
    args = parser.parse_args()
    echo_env_status(args.keyfile)


if __name__ == '__main__':
    main()
