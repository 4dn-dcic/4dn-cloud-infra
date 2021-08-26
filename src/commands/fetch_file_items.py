from dcicutils import ff_utils
import argparse
import json
import sys


EPILOG = __doc__


class FastqFetcher:

    remove_fields = ['schema_version', 'date_created', 'last_modified', 'submitted_by', 'quality_metric']

    def __init__(self, case_accession, old_env_key, new_env_key=None, write=True, outfile='files.json'):
        self.case_accession = case_accession
        self.old_env_key = old_env_key
        self.new_env_key = new_env_key
        self.write = write
        self.outfile = outfile
        self.case_metadata = ff_utils.get_metadata(f'/cases/{self.case_accession}/', key=self.old_env_key)
        self.sample_ids = [
            sample['@id'] for sample in self.case_metadata.get('sample_processing', {}).get('samples', [{}])
        ]
        if not self.sample_ids:
            print('No samples found for Case')
            sys.exit()
        self.fastq_files = []
        self.cram_files = []
        self.json_out = {'file_fastq': [], 'file_processed': []}
        self.get_files_from_samples()
        self.get_file_json()
        print(f'Found {len(self.json_out["file_fastq"])} fastq files, '
              f'{len(self.json_out["file_fastq"])} cram files')
        if self.write:
            print(f'Writing json data to {self.outfile}')
            self.write_json()
        if self.new_env_key:
            self.post_files()
        else:
            print('No posts performed.')

    def get_files_from_samples(self):
        for sample_id in self.sample_ids:
            sample = ff_utils.get_metadata(sample_id + '?frame=object', key=self.old_env_key)
            self.fastq_files.extend(sample.get('files', []))
            self.cram_files.extend(sample.get('cram_files', []))

    def get_file_json(self):
        for fastq in self.fastq_files:
            fastq_metadata = ff_utils.get_metadata(fastq + '?frame=raw', key=self.old_env_key)
            for field in self.remove_fields:
                if field in fastq_metadata:
                    del fastq_metadata[field]
            self.json_out['file_fastq'].append(fastq_metadata)
        for cram in self.cram_files:
            cram_metadata = ff_utils.get_metadata(cram + '?frame=raw', key=self.old_env_key)
            for field in self.remove_fields:
                if field in cram_metadata:
                    del cram_metadata[field]
            self.json_out['file_processed'].append(cram_metadata)

    def write_json(self):
        with open(self.outfile, 'w') as json_file:
            json.dump(self.json_out, json_file, indent=4)

    def post_files(self):
        results_dict = {
            'post': {
                'file_fastq': {'success': 0, 'fail': 0},
                'file_processed': {'success': 0, 'fail': 0}
            },
            'patch': {'success': 0, 'fail': 0},
        }

        # Posting files (without file relations)
        print('Posting file metadata...')
        related_files = {}
        for k, v in self.json_out.items():
            for item in v:
                post_body = {k: v for k, v in item.items() if k != 'related_files'}
                related_files[item['uuid']] = {
                    'related_files': item.get('related_files')
                }
                try:
                    resp = ff_utils.post_metadata(post_body, k, key=self.new_env_key)
                except Exception:
                    results_dict['post'][k]['fail'] += 1
                else:
                    if resp['status'] == 'success':
                        results_dict['post'][k]['success'] += 1
                    else:
                        results_dict['post'][k]['fail'] += 1
        print(f'fastq files: {results_dict["post"]["file_fastq"]["success"]} success, '
              f'{results_dict["post"]["file_fastq"]["fail"]} fail')
        print(f'cram files: {results_dict["post"]["file_processed"]["success"]} success, '
              f'{results_dict["post"]["file_processed"]["fail"]} fail')

        # Patching file relations
        print('Patching file relations...')
        for k, v in related_files.items():
            try:
                resp = ff_utils.patch_metadata(v, k, key=self.new_env_key)
            except Exception:
                results_dict['patch']['fail'] += 1
            else:
                if resp['status'] == 'success':
                    results_dict['patch']['success'] += 1
                else:
                    results_dict['patch']['fail'] += 1
        print(f'file relation patching: {results_dict["patch"]["success"]} success, '
              f'{results_dict["patch"]["fail"]} fail')


def main():
    """
    Used for fetching fastqs associated with a case on one cgap environment, and writing out to a json file
    or posting to a new env. By default does not post and just writes to a default filename.

    Note: this requires project, institution, file_format items to be loaded with the same uuids as fetch environment.

    Example usage 1:
    python fetch_file_items.py GAPCAKQB9FPJ

    Example usage 2:
    python fetch_file_items.py GAPCAKQB9FPJ --post --keyfile ../.cgap-keys.json --keyname-from fourfront-cgapwolf \
        --keyname-to fourfront-cgaptest
    """
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is invalid
        description="Load fastq files from a case on one environment to a new environment", epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('accession', help="Case Accession")
    parser.add_argument('--post', default=False, action="store_true",
                        help="If true, file metadata will be posted to server specified in --keyname-to")
    parser.add_argument('--outfile', default='files.json', help="Specify filename to write json output to")
    parser.add_argument('--keyfile', default='.cgap-keys.json', help="path to keyfile")
    parser.add_argument('--keyname-from', default='cgap',
                        help="Name of key in keyfile that files will be fetched from")
    parser.add_argument('--keyname-to', default=None,
                        help="Name of key in keyfile that file metadata will be posted to, required with --post")
    args = parser.parse_args()

    if args.post and not args.keyname_to:
        print('For posting to an env, the key for posting must be specified in --keyname-to. Please try again.')
        exit(1)

    with open(args.keyfile) as keyfile:
        keys = json.load(keyfile)
        old_env_key = keys[args.keyname_from]
        if args.keyname_to:
            new_env_key = keys[args.keyname_to]
        else:
            new_env_key = None

    FastqFetcher(args.accession, old_env_key, new_env_key, outfile=args.outfile)


if __name__ == '__main__':
    main()
