"""CLI helpers for the optional Foursight Chalice pruning controls.

The values returned here are the explicit, environment-independent contract consumed
by the compatible foursight-core packaging API.
"""


PRUNING_VARIANTS = ('all', 'cgap', 'fourfront', 'smaht')


def pruning_options_from_args(args):
    """Return direct foursight-core pruning kwargs, or ``None`` by default.

    The ``enabled=False`` CLI meaning is represented by foursight-core's
    ``skip_prune=True`` keyword.  Returning no kwargs for the default path
    preserves the historical packaging call and its defaults.
    """
    options = {}
    if getattr(args, 'no_prune', False):
        options['enabled'] = False
    if getattr(args, 'prune_dry_run', False):
        options['dry_run'] = True
    if getattr(args, 'prune_report', False):
        options['report'] = True
    variant = getattr(args, 'prune_variant', None)
    if variant is not None:
        options['variant'] = variant
    if not options:
        return None
    return {
        'dry_run': options.get('dry_run', False),
        'report': options.get('report', False),
        'variant': options.get('variant'),
        'skip_prune': options.get('enabled') is False,
    }


def should_upload_after_pruning(upload_change_set, prune_dry_run):
    """Return false for a dry-run preview, regardless of upload request."""
    return bool(upload_change_set and not prune_dry_run)


def add_pruning_arguments(parser):
    """Add the opt-in pruning controls to an argparse provision parser."""
    pruning_group = parser.add_argument_group('Chalice package pruning (Foursight only)')
    pruning_modes = pruning_group.add_mutually_exclusive_group()
    pruning_modes.add_argument(
        '--prune-dry-run', '--foursight-prune-dry-run', '--dry-run',
        dest='prune_dry_run', action='store_true',
        help='Preview pruning and report candidates without changing deployment.zip; '
             'also prevents package upload and change-set creation')
    pruning_group.add_argument(
        '--prune-report', '--foursight-prune-report', '--report',
        dest='prune_report', action='store_true',
        help='Report each item selected by the Chalice pruning rules')
    pruning_group.add_argument(
        '--prune-variant', '--foursight-variant', '--application-variant', '--variant',
        dest='prune_variant', choices=PRUNING_VARIANTS,
        help='Select the Foursight application variant for pruning (default: retain all)')
    pruning_modes.add_argument(
        '--no-prune', '--disable-pruning', '--skip-pruning',
        dest='no_prune', action='store_true',
        help='Bypass Chalice package pruning for troubleshooting')
    return parser
