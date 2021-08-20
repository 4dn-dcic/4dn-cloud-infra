import argparse
import glob
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


EPILOG = __doc__

CREDS_PATH = os.path.expanduser('~/.cgap-keys.json')
KNOWLEDGE_BASE_DIR = 'test_data/knowledge_base'
KB_INSERTS_FILE = 'temp-local-inserts'
KB_INSERTS_DIR = os.path.join(KNOWLEDGE_BASE_DIR, KB_INSERTS_FILE)
KB_ZIP_FILE = 'knowledge_base.zip'
KB_ZIP_PATH = os.path.join(KNOWLEDGE_BASE_DIR, KB_ZIP_FILE)
HIGLASS_BASE = ['higlass_view_config.json']
GENES_BASE =  ['gene.json']
DISORDER_BASE = ['disorder.json']
PHENOTYPE_BASE = ['phenotype.json']
VARIANT_CONSEQUENT_BASE = ['variant_consequence.json']

BASES = {
    'higlass': HIGLASS_BASE,
    'genes': GENES_BASE,
    'disorder': DISORDER_BASE,
    'phenotype': PHENOTYPE_BASE,
    'variant_consequent': VARIANT_CONSEQUENT_BASE,
}
ALL_BASE_NAMES = list(BASES.keys())
DEFAULT_INCLUDE_BASES = 'all'


def resume_point(file, server, env_name=DEFAULT_ENV_NAME):
    item_kind = os.path.splitext(os.path.basename(file))[0]
    item_key = snake_case_to_camel_case(item_kind)
    return int(requests.get(f"{server}/counts?format=json").json()['db_es_compare'][item_key].split()[1])


def resolve_env_name_server_creds(env_name, server):
    if env_name and server:
        raise ValueError("You may not specify both env_name and server.")

    with io.open(CREDS_PATH) as keyfile:
        all_creds = json.load(keyfile)

    if env_name is None and server is None:
        env_name = DEFAULT_ENV_NAME

    if env_name:
        env_creds = all_creds.get(env_name)
        if env_creds is None:
            raise ValueError(f"Missing credentials for {env_name} in {CREDS_PATH}.")
        env_server = env_creds['server']

    elif server:
        server_to_find = server.rstrip('/')
        for name, creds in all_creds.items():
            creds_server = creds.get('server')
            if creds_server == server_to_find:
                env_name = name
                env_server = creds_server
                env_creds = creds
                break
        else: # IMPORTANT: This is an 'else' on the 'for', in case it gets to end not finding something.
            raise ValueError(f"Missing server {server_to_find} in {CREDS_PATH}.")

    else:
        raise RuntimeError("Should not be able to get to this code.")

    return env_name, env_server, env_creds


def load_knowledge_base(env_name=None, include_bases=None, confirm=True, start=0, resume=False, server=None):
    """ Must be invoked from top level - reads the 3 knowledge base files (provided in zip). """

    if start is None:
        start = 0
    else:  # start is not None
        if resume:
            PRINT("You cannot specify both resume and start.")
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
    maybe_continue_to_be = "continue to " if resume else ""
    print(f"{n_of(included_files, 'file')} will {maybe_continue_to_be}be loaded: {conjoined_list(included_files)}.")

    try:
        env_name, server, creds = resolve_env_name_server_creds(env_name, server)
    except Exception as e:
        PRINT(str(e))
        return

    if confirm and not y_or_n(f"Load data to {env_name} server {server}", default=True):
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

    for file in included_files:
        with io.open('/'.join([KB_INSERTS_DIR, file])) as collection_meta:
            items = json.load(collection_meta)
            if resume:
                start = resume_point(file, server=server, env_name=env_name)
                PRINT(f"Resuming load of {file} from inferred position {start}.")
            elif start > 0:
                PRINT(f"Resuming load of {file} from specified position {start}.")
            items = items[start:]
            for item in tqdm(items):
                try:
                    ff_utils.post_metadata(item, file.split('.')[0].title().replace('_', ''), key=creds)
                except Exception as e:
                    print(e)
        start = 0


def main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Load the knowledge base.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env-name", dest="env_name", default=None,
                        help=f"name of environment to load args into (default {DEFAULT_ENV_NAME}"
                             f" unless --server given)")
    parser.add_argument("--server", default=None,
                        help="name of server to find and use, instead of specifying an env_name")
    parser.add_argument("--start", default=None, type=int,
                        help=f"insert position to start at, for error recovery only (default 0)")
    parser.add_argument("--resume", default=False, action="store_true",
                        help="whether to resume from last known position (default if omitted is to start from 0)")
    parser.add_argument("--include-bases", default=DEFAULT_INCLUDE_BASES, dest="include_bases",
                        help=(f"comma-separated name(s) of bases to include"
                              f" ({disjoined_list(ALL_BASE_NAMES, conjunction='and/or')},"
                              f" default {DEFAULT_INCLUDE_BASES})"))
    parser.add_argument("--no-confirm", dest="no_confirm", default=False, action="store_true",
                        help="whether to ask for confirmation (default if omitted is to ask for confirmation)")
    args = parser.parse_args(args=simulated_args)

    load_knowledge_base(env_name=args.env_name, confirm=not args.no_confirm, include_bases=args.include_bases,
                        start=args.start, resume=args.resume, server=args.server)


if __name__ == '__main__':
    main()
