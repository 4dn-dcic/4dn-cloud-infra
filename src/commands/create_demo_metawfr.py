import argparse
from dcicutils import s3Utils
from magma_ff import create_metawfr


EPILOG = __doc__


def main():
    """ Creates a metawfr for the NA12879 case.
        Requires an already submitted case.
        See: https://magma-suite.readthedocs.io/en/latest/ff_functions.html
    """
    parser = argparse.ArgumentParser(  # noqa - PyCharm wrongly thinks the formatter_class is invalid
        description="Builds metawfr for demo case", epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument('case_uuid', help='uuid for case')
    parser.add_argument('analysis_type', default='WGS trio',
                        help='Analysis type for this metawfr')
    parser.add_argument('--post-metawfr', default=False, action='store_true',
                        help='If true, will post metawfr to portal')
    parser.add_argument('--patch-case', default=False, action='store_true',
                        help='If true, will patch metawfr info to case')
    args = parser.parse_args()
    ff_key = s3Utils().get_ff_key()
    return create_metawfr.create_metawfr_from_case(
        '', args.case_uuid, args.analysis_type, ff_key, post=args.post_metawfr,
        patch_case=args.patch_case, verbose=True
    )


if __name__ == '__main__':
    main()
