import argparse
import io
import json
import os
import subprocess

from dcicutils import ff_utils
from dcicutils.command_utils import y_or_n
from dcicutils.lang_utils import conjoined_list
from dcicutils.misc_utils import PRINT
from tqdm import tqdm
from ..base import ConfigManager, ENV_NAME as DEFAULT_ENV_NAME
from ..parts.ecs import C4ECSApplicationExports


EPILOG = __doc__

DEFAULT_PATH_TO_CREDS = os.path.expanduser('~/.cgap-keys.json')
KNOWLEDGE_BASE_DIR = 'test_data/knowledge_base'
KB_INSERTS_FILE = 'temp-local-inserts'
KB_INSERTS_DIR = os.path.join(KNOWLEDGE_BASE_DIR, KB_INSERTS_FILE)
KB_ZIP_FILE = 'knowledge_base.zip'
KB_ZIP_PATH = os.path.join(KNOWLEDGE_BASE_DIR, KB_ZIP_FILE)
# Computed instead.
# SERVER = 'http://c4ecstrialalphacgapmastertest-273357903.us-east-1.elb.amazonaws.com'
HIGLASS_BASE = ['higlass_view_config.json']
GENES_BASE = ['variant_consequence.json', 'gene.json', 'disorder.json', 'phenotype.json']
BASES = {
    'higlass': HIGLASS_BASE,
    'genes': GENES_BASE,
}

DEFAULT_CURRENT_BASE = 'higlass'


def load_knowledge_base(env_name=None,
                        path_to_creds=None,
                        include_bases=None,
                        # current_base=None,
                        # include_genes=False,
                        confirm=True):
    """ Must be invoked from top level - reads the 3 knowledge base files (provided in zip). """

    env_name = env_name or DEFAULT_ENV_NAME
    # Precondition: both of these must exist
    path_to_creds = path_to_creds or DEFAULT_PATH_TO_CREDS
    # SERVER = 'http://c4ecstrialalphacgapmastertest-273357903.us-east-1.elb.amazonaws.com'
    if include_bases == 'all':
        include_bases = ",".join(BASES.keys())
    print(f"Including data for {conjoined_list(include_bases.split(','))}.")
    current_base = sum([BASES[key] for key in include_bases.split(',')], [])
    print(f"Loading {conjoined_list(current_base)}.")

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

    with io.open(path_to_creds) as keyfile:
        creds = json.load(keyfile)

    keys = None
    server_to_find = application_url.rstrip('/')
    for keydict in creds.values():
        if keydict['server'].rstrip('/') == server_to_find:
            keys = keydict
            break
    if keys is None:
        raise Exception('Did not locate specified server, check creds file.')

    for file in current_base:
        with io.open('/'.join([KB_INSERTS_DIR, file])) as collection_meta:
            items = json.load(collection_meta)
            for item in tqdm(items):
                try:
                    ff_utils.post_metadata(item, file.split('.')[0].title().replace('_', ''), key=keys)
                except Exception as e:
                    print(e)


def main(simulated_args=None):
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
        description="Load the knowledge base.",
        epilog=EPILOG,  formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env_name", default=None, help="name of environment to load args into")
    parser.add_argument("--include-bases", default=DEFAULT_CURRENT_BASE, help="name of environment to load args into")
    parser.add_argument("--no-confirm", default=False, action="store_true", help="whether to include genes",
                        dest="no_confirm")
    args = parser.parse_args(args=simulated_args)

    load_knowledge_base(env_name=args.env_name, confirm=not args.no_confirm, include_bases=args.include_bases)


if __name__ == '__main__':
    main()
