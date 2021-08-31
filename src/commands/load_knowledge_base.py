import argparse
import glob
import io
import json
import os
import requests
import subprocess

from dcicutils import ff_utils
from dcicutils.command_utils import y_or_n
from dcicutils.lang_utils import conjoined_list, disjoined_list, there_are, string_pluralize
from dcicutils.misc_utils import PRINT, snake_case_to_camel_case, find_association, find_associations
from tqdm import tqdm
from ..base import ENV_NAME as DEFAULT_ENV_NAME


EPILOG = __doc__


def maybe_plural(n, thing):  # move to dcicutils.lang_utils
    if not isinstance(n, int):
        n = len(n)
    return thing if n == 1 else string_pluralize(thing)


class KnowledgeBase:

    CREDS_PATH = os.path.expanduser('~/.cgap-keys.json')
    KNOWLEDGE_BASE_PATH = 'test_data/knowledge_base'
    KB_INSERTS_DIRNAME = 'temp-local-inserts'
    KB_INSERTS_PATH = os.path.join(KNOWLEDGE_BASE_PATH, KB_INSERTS_DIRNAME)
    KB_ZIP_FILE = 'knowledge_base.zip'
    KB_ZIP_PATH = os.path.join(KNOWLEDGE_BASE_PATH, KB_ZIP_FILE)
    DEFAULT_INCLUDE = 'all'

    TEST_DATA_INSERTS = None
    TEST_DATA_TYPES = None
    TEST_DATA_TYPE_TO_INSERTS_MAPPINGS = None

    @classmethod
    def initialize(cls):

        if not os.path.exists(cls.KB_INSERTS_PATH) and os.path.exists(cls.KB_ZIP_PATH):
            PRINT(f"Unzipping {cls.KB_ZIP_PATH}...")
            subprocess.run(f"pushd {cls.KNOWLEDGE_BASE_PATH};"
                           f" unzip {cls.KB_ZIP_FILE};"
                           f" ls -dal {cls.KB_INSERTS_DIRNAME};"
                           f" popd",
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True, executable='/bin/bash')
            cls.initialize()  # Need to look again at available types
            PRINT(f"Done unzipping {cls.KB_ZIP_PATH}.")

        cls.TEST_DATA_INSERTS = sorted(glob.glob(os.path.join(cls.KB_INSERTS_PATH, "*")))
        cls.TEST_DATA_TYPES = [
            os.path.splitext(os.path.basename(file))[0]
            for file in cls.TEST_DATA_INSERTS
        ]
        cls.TEST_DATA_TYPE_TO_INSERTS_MAPPINGS = [
            {
                'type': data_type,
                # 'inserts_path': inserts_file,
                'inserts_file': os.path.basename(inserts_file),
            }
            for data_type, inserts_file in zip(cls.TEST_DATA_TYPES, cls.TEST_DATA_INSERTS)
        ]

    @classmethod
    def resume_point(cls, file, server):
        item_kind = os.path.splitext(os.path.basename(file))[0]
        item_key = snake_case_to_camel_case(item_kind)
        return int(requests.get(f"{server}/counts?format=json").json()['db_es_compare'][item_key].split()[1])

    @classmethod
    def resolve_env_name_server_creds(cls, env_name, server):
        if env_name and server:
            raise ValueError("You may not specify both env_name and server.")

        with io.open(cls.CREDS_PATH) as keyfile:
            all_creds = json.load(keyfile)

        if env_name is None and server is None:
            env_name = DEFAULT_ENV_NAME

        if env_name:
            env_creds = all_creds.get(env_name)
            if env_creds is None:
                raise ValueError(f"Missing credentials for {env_name} in {cls.CREDS_PATH}.")
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
            else:  # IMPORTANT: This is an 'else' on the 'for', in case it gets to end not finding something.
                raise ValueError(f"Missing server {server_to_find} in {cls.CREDS_PATH}.")

        else:
            raise RuntimeError("Should not be able to get to this code.")

        return env_name, env_server, env_creds

    @classmethod
    def load(cls, env_name=None, include=None, confirm=True, start=0, resume=False, server=None, show_list=False):
        """ Must be invoked from top level - reads the 3 knowledge base files (provided in zip). """

        if show_list:
            PRINT(f"Known types (from in {cls.KB_INSERTS_PATH}) are:")
            col1_wid = max([len(entry['type']) for entry in cls.TEST_DATA_TYPE_TO_INSERTS_MAPPINGS])
            for entry in cls.TEST_DATA_TYPE_TO_INSERTS_MAPPINGS:
                print(f"{entry['type'].ljust(col1_wid)} => {entry['inserts_file']}")
            return

        if start is None:
            start = 0
        else:  # start is not None
            if resume:
                PRINT("You cannot specify both resume and start.")
                return
            elif start < 0:
                PRINT("Start must be greater than or equal to zero.")
                return

        include = cls.DEFAULT_INCLUDE if include is None else include
        env_name = env_name or DEFAULT_ENV_NAME
        if include == 'all':
            include = ",".join(cls.TEST_DATA_TYPES)
        if not include:
            PRINT("Nothing to load.")
            return
        included_types = include.split(",")
        included_files = []
        seen_types = set()
        unknown_types = set()
        duplicate_types = set()
        ambiguous_types = set()
        for include_type in included_types:
            if include_type in seen_types:
                duplicate_types.add(include_type)
            entries = find_associations(cls.TEST_DATA_TYPE_TO_INSERTS_MAPPINGS,
                                        type=lambda x: x.startswith(include_type))
            if len(entries) == 1:
                entry = entries[0]
                included_files.append(entry['inserts_file'])
            elif not entries:
                unknown_types.add(include_type)
            else:
                # In principle, find_association could throw an ambiguity error, but the file system can't have two
                # files with the same name, so we know it won't. -kmp 21-Aug-2021
                entry = find_association(cls.TEST_DATA_TYPE_TO_INSERTS_MAPPINGS, type=include_type)
                if entry:  # allow an exact match to overcome a substring ambiguity
                    included_files.append(entry['inserts_file'])
                    continue
                matches = [entry['type'] for entry in entries]
                ambiguous_types.add(f"{include_type} (could be any of {disjoined_list(matches)})")
            seen_types.add(include_type)
        if unknown_types:
            PRINT(there_are(unknown_types, kind="unknown include type", punctuate=True))
            PRINT(f"Known types are {conjoined_list(cls.TEST_DATA_TYPES)}. See {cls.KB_INSERTS_PATH}.")
            # Will return farther down
        if duplicate_types:
            PRINT(there_are(duplicate_types, kind="duplicated include type", punctuate=True))
            # Will return farther down
        if ambiguous_types:
            PRINT(there_are(ambiguous_types, kind="ambiguous include type", punctuate=True))
            # Will return farther down
        if unknown_types or duplicate_types or ambiguous_types:
            return
        maybe_the_rest_of = "the rest of " if resume else ""
        print(f"Including data from {maybe_the_rest_of}{maybe_plural(included_files, 'inserts file')}"
              f" {conjoined_list([os.path.basename(file) for file in included_files])}.")

        try:
            env_name, server, creds = cls.resolve_env_name_server_creds(env_name, server)
        except Exception as e:
            PRINT(str(e))
            return

        if confirm and not y_or_n(f"Load this data to {env_name} server {server}", default=True):
            PRINT("Aborted.")
            return

        if not os.path.exists(cls.KB_INSERTS_PATH):
            PRINT(f"Missing inserts path: {cls.KB_INSERTS_PATH}")
            return

        for included_file in included_files:
            with io.open(os.path.join(cls.KB_INSERTS_PATH, included_file)) as collection_meta:
                items = json.load(collection_meta)
                if resume:
                    start = cls.resume_point(included_file, server=server)
                    PRINT(f"Resuming load of {included_file} from inferred position {start}.")
                elif start > 0:
                    PRINT(f"Resuming load of {included_file} from specified position {start}.")
                items = items[start:]
                for item in tqdm(items):
                    try:
                        ff_utils.post_metadata(item, included_file.split('.')[0].title().replace('_', ''), key=creds)
                    except Exception as e:
                        print(e)
            start = 0

    @classmethod
    def main(cls, simulated_args=None):
        KnowledgeBase.initialize()
        parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is specified wrong here.
            description="Load the knowledge base.",
            epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument("--env-name", dest="env_name", default=None,
                            help=f"name of environment to load args into (default {DEFAULT_ENV_NAME}"
                                 f" unless --server given)")
        parser.add_argument("--list", dest="show_list", default=False, action="store_true",
                            help="Whether to just list available types rather than load them (default False).")
        parser.add_argument("--server", default=None,
                            help="name of server to find and use, instead of specifying an env_name")
        parser.add_argument("--start", default=None, type=int,
                            help=f"insert position to start at, for error recovery only (default 0)")
        parser.add_argument("--resume", default=False, action="store_true",
                            help="whether to resume from last known position (default if omitted is to start from 0)")
        parser.add_argument("--include", default=cls.DEFAULT_INCLUDE,
                            help=(f"comma-separated name(s) of test data groups to include"
                                  f" ({disjoined_list(cls.TEST_DATA_TYPES, conjunction='and/or')},"
                                  f" default {cls.DEFAULT_INCLUDE})."
                                  f" It is sufficient to use unique subtrings."))
        parser.add_argument("--no-confirm", dest="no_confirm", default=False, action="store_true",
                            help="whether to ask for confirmation (default if omitted is to ask for confirmation)")
        args = parser.parse_args(args=simulated_args)

        KnowledgeBase.load(env_name=args.env_name, confirm=not args.no_confirm, include=args.include,
                           start=args.start, resume=args.resume, server=args.server, show_list=args.show_list)


def main(simulated_args=None):
    KnowledgeBase.main(simulated_args=simulated_args)


if __name__ == '__main__':
    main()
