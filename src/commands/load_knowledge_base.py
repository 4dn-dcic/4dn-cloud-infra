import argparse
import io
import json
import os
import requests
import subprocess

from dcicutils import ff_utils
from dcicutils.command_utils import y_or_n
from dcicutils.lang_utils import conjoined_list, disjoined_list, n_of
from dcicutils.misc_utils import PRINT, snake_case_to_camel_case
from tqdm import tqdm
from ..base import ENV_NAME as DEFAULT_ENV_NAME
from ..parts.ecs import C4ECSApplicationExports


EPILOG = __doc__

CREDS_PATH = os.path.expanduser('~/.cgap-keys.json')
KNOWLEDGE_BASE_DIR = 'test_data/knowledge_base'
KB_INSERTS_FILE = 'temp-local-inserts'
KB_INSERTS_DIR = os.path.join(KNOWLEDGE_BASE_DIR, KB_INSERTS_FILE)
KB_ZIP_FILE = 'knowledge_base.zip'
KB_ZIP_PATH = os.path.join(KNOWLEDGE_BASE_DIR, KB_ZIP_FILE)
HIGLASS_BASE = ['higlass_view_config.json']
GENES_BASE = ['gene.json']  # ['variant_consequence.json', 'gene.json', 'disorder.json', 'phenotype.json']
BASES = {
    'higlass': HIGLASS_BASE,
    'genes': GENES_BASE,
}
ALL_BASE_NAMES = list(BASES.keys())
DEFAULT_INCLUDE_BASES = 'higlass'


def load_knowledge_base(env_name=None, include_bases=None, confirm=True, start=0, restart=False):
    """ Must be invoked from top level - reads the 3 knowledge base files (provided in zip). """

    if start is None:
        start = 0
    else:  # start is not None
        if restart:
            PRINT("You cannot specify both restart and start.")
            return
        elif start < 0:
            PRINT("Start must be greater than or equal to zero.")
            return

    include_bases = DEFAULT_INCLUDE_BASES if include_bases is None else include_bases
    env_name = env_name or DEFAULT_ENV_NAME
    if include_bases == 'all':
        include_bases = ",".join(ALL_BASE_NAMES)
    if not include_bases:
        PRINT("Nothing to load.")
        return
    included_bases = include_bases.split(",")
    for base in included_bases:
        if base not in BASES:
            PRINT(f"Invalid base {base!r}. It must be one of {disjoined_list(ALL_BASE_NAMES)}.")
            return
    print(f"Including data for {conjoined_list(included_bases)}.")
    included_files = sum([BASES[key] for key in included_bases], [])
    maybe_continue_to_be = "continue to " if restart else ""
    print(f"{n_of(included_files, 'file')} will {maybe_continue_to_be}be loaded: {conjoined_list(included_files)}.")
    application_url = C4ECSApplicationExports.get_application_url(env_name)
    if confirm and not y_or_n(f"Load data to {env_name} server {application_url}", default=True):
        PRINT("Aborted.")
        return

    if not os.path.exists(KB_INSERTS_DIR) and os.path.exists(KB_ZIP_PATH):
        print(f"Unzipping {KB_ZIP_PATH}...")
        subprocess.run(f"pushd {KNOWLEDGE_BASE_DIR}; unzip {KB_ZIP_FILE}; ls -dal {KB_INSERTS_FILE}; popd",
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, executable='/bin/bash')
        PRINT(f"Done unzipping {KB_ZIP_PATH}.")

    if not os.path.exists(KB_INSERTS_DIR):
        PRINT(f"Missing inserts path: {KB_INSERTS_DIR}")
        return

    with io.open(CREDS_PATH) as keyfile:
        creds = json.load(keyfile)

    keys = None
    server_to_find = application_url.rstrip('/')
    for keydict in creds.values():
        if keydict['server'].rstrip('/') == server_to_find:
            keys = keydict
            break
    if keys is None:
        raise Exception('Did not locate specified server, check creds file.')

    for file in included_files:
        with io.open('/'.join([KB_INSERTS_DIR, file])) as collection_meta:
            items = json.load(collection_meta)
            if restart:
                start = restart_point(file, env_name=env_name)
                PRINT(f"Restarting load of {file} from inferred position {start}.")
            elif start > 0:
                PRINT(f"Restarting load of {file} from specified position {start}.")
            items = items[start:]
            for item in tqdm(items):
                try:
                    ff_utils.post_metadata(item, file.split('.')[0].title().replace('_', ''), key=keys)
                except Exception as e:
                    print(e)
        start = 0


def restart_point(file, env_name=DEFAULT_ENV_NAME):
    application_url = C4ECSApplicationExports.get_application_url(env_name)
    item_kind = os.path.splitext(os.path.basename(file))[0]
    item_key = snake_case_to_camel_case(item_kind)
    return int(requests.get(f"{application_url}/counts?format=json").json()['db_es_compare'][item_key].split()[1])


def main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Load the knowledge base.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env_name", default=DEFAULT_ENV_NAME,
                        help=f"name of environment to load args into (default {DEFAULT_ENV_NAME})")
    parser.add_argument("--start", default=None, type=int,
                        help=f"insert position to start at, for error recovery only (default 0)")
    parser.add_argument("--restart", default=False, action="store_true",
                        help="whether to restart from last known position (default if omitted is to start from 0)")
    parser.add_argument("--include-bases", default=DEFAULT_INCLUDE_BASES,
                        help=(f"comma-separated name(s) of bases to include"
                              f" ({disjoined_list(ALL_BASE_NAMES, conjunction='and/or')},"
                              f" default {DEFAULT_INCLUDE_BASES})"))
    parser.add_argument("--no-confirm", dest="no_confirm", default=False, action="store_true",
                        help="whether to ask for confirmation (default if omitted is to ask for confirmation)")
    args = parser.parse_args(args=simulated_args)

    load_knowledge_base(env_name=args.env_name, confirm=not args.no_confirm, include_bases=args.include_bases,
                        start=args.start, restart=args.restart)


if __name__ == '__main__':
    main()
