import argparse
from dcicutils import s3Utils
from dcicutils.misc_utils import PRINT
from magma_ff import create_metawfr


EPILOG = __doc__
WGS_TRIO_METAWF = '6a6f293c-21a9-428b-8ddd-ee29e2c8a1df'  # this value shouldn't change
CNV_TRIO_METAWF = '9da76c35-732a-40e8-b55e-7f929a636dc2'

SUPPORTED_ANALYSIS_TYPES = {
    'WGS trio': WGS_TRIO_METAWF,
    'SV trio': CNV_TRIO_METAWF
}


def main():
    """ Creates a metawfr for the NA12879 case.
        Requires an already submitted case.
        Note that this command only support WGS trio analysis at this time.
        See: https://magma-suite.readthedocs.io/en/latest/ff_functions.html
    """
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is invalid
        description="Builds metawfr for demo case", epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('case_uuid', help='uuid for case')
    parser.add_argument('--analysis-type', default='WGS trio',
                        help='Analysis type for this metawfr',
                        choices=list(SUPPORTED_ANALYSIS_TYPES.keys()))
    parser.add_argument('--post-metawfr', default=False, action='store_true',
                        help='If true, will post metawfr to portal')
    parser.add_argument('--patch-case', default=False, action='store_true',
                        help='If true, will patch metawfr info to case')
    args = parser.parse_args()
    if args.analysis_type not in SUPPORTED_ANALYSIS_TYPES:
        raise Exception('Does not handle non-trio analysis')
    ff_key = s3Utils().get_ff_key()
    metawfr_json = create_metawfr.create_metawfr_from_case(
        SUPPORTED_ANALYSIS_TYPES[args.analysis_type], args.case_uuid, args.analysis_type, ff_key, post=args.post_metawfr,
        patch_case=args.patch_case, verbose=True
    )
    PRINT(metawfr_json)
    exit(0)


if __name__ == '__main__':
    main()
