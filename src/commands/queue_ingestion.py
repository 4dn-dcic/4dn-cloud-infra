import io
import os
import json
from dcicutils import ff_utils


# Precondition: both of these must exist
PATH_TO_CREDS = os.path.expanduser('~/.cgap-keys.json')
PATH_TO_VCF_META = 'test_data/na_12879/file_processed.json'
SERVER = 'http://c4ecstrialalphacgapmastertest-273357903.us-east-1.elb.amazonaws.com'


def main():
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

    with io.open(PATH_TO_VCF_META) as item_meta:
        uuid = json.load(item_meta)['uuid']

    response = ff_utils.post_metadata({
        'uuids': [uuid]
    }, 'queue_ingestion', key=keys)
    print(response)


if __name__ == '__main__':
    main()
