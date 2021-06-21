import io
import os
from tqdm import tqdm
import json
from dcicutils import ff_utils

# Precondition: both of these must exist
PATH_TO_CREDS = os.path.expanduser('~/.cgap-keys.json')
PATH_TO_KNOWLEDGE_BASE = 'test_data/knowledge_base/temp-local-inserts'
SERVER = 'http://c4ecstrialalphacgapmastertest-273357903.us-east-1.elb.amazonaws.com'
CURRENT_BASE = ['higlass_view_config.json']  # ['variant_consequence.json', 'gene.json', 'disorder.json', 'phenotype.json']


def main():
    """ Must be invoked from top level - reads the 3 knowledge base files (provided in zip). """
    with io.open(PATH_TO_CREDS) as keyfile:
        creds = json.load(keyfile)

    keys = None
    server_to_find = SERVER.rstrip('/')
    for keydict in creds.values():
        if keydict['server'].rstrip('/') == server_to_find:
            keys = keydict
            break
    if keys is None:
        raise Exception('Did not locate specified server, check creds file.')

    for file in CURRENT_BASE:
        with io.open('/'.join([PATH_TO_KNOWLEDGE_BASE, file])) as collection_meta:
            items = json.load(collection_meta)
            for item in tqdm(items):
                try:
                    ff_utils.post_metadata(item, file.split('.')[0].title().replace('_', ''), key=keys)
                except Exception as e:
                    print(e)


if __name__ == '__main__':
    main()
