Chalice package pruning controls and deployment rules
=====================================================

Foursight provisioning keeps its historical pruning behavior by default. The optional
``provision`` controls below are useful when investigating package contents::

    poetry run cli provision foursight --prune-dry-run --prune-report \
        --prune-variant cgap

``--prune-dry-run`` previews pruning without replacing ``deployment.zip``. It also prevents
package upload and CloudFormation change-set creation, even if ``--upload-change-set`` was
supplied. Use ``--prune-report`` for one line per removal candidate. ``--prune-variant`` accepts
``all``, ``cgap``, ``fourfront``, or ``smaht``; selecting a variant permits the packager to remove
the other application roots. ``--no-prune`` bypasses pruning for troubleshooting. Dry-run and
no-prune are mutually exclusive.

When a pruning control is selected, cloud-infra forwards direct ``dry_run``, ``report``,
``variant``, and ``skip_prune`` keyword arguments to the compatible foursight-core packaging API.
The normal path passes no pruning keywords, preserving its existing call shape and defaults.

Script behavior
---------------

``scripts/prune_chalice_package.sh`` removes known build/provisioning packages from a Chalice
deployment archive after the archive has been built. The existing removal of nested ``test``,
``tests``, and ``examples`` directories is retained. Package removal is an explicit allow-list;
the script does not delete files based on static-import analysis.

The original one-argument invocation remains supported::

    scripts/prune_chalice_package.sh path/to/deployment.zip

Use ``--dry-run --report`` to inspect the proposed removals without changing the archive. Dry-run
performs the removals and rebuilds a temporary archive in the extracted workspace, then reports the
post-removal uncompressed size and a projected compressed size/delta. The projected compressed size
is approximate because temporary rebuild metadata and compression can differ from production.
Use ``--variant cgap``, ``--variant fourfront``, or ``--variant smaht`` only when the archive is
known to contain the selected ``chalicelib_*`` implementation. A variant removes the other
``chalicelib_*`` roots; without a variant, all application variants are retained for compatibility
with the runtime selection in ``app.py``.

The ``chalice`` and ``tibanna`` runtime roots, including their distribution metadata, are kept.
The current package-removal allow-list is limited to ``awacs`` and ``troposphere``; extend it only
after confirming the package is not needed by either deployed Foursight variant.

Runtime-risk assumptions
------------------------

* ``app.py`` selects a Foursight implementation at runtime, and Foursight may use dynamic imports.
  The package allow-list must therefore be reviewed when runtime configuration or plugin loading
  changes.
* A package that is unused by 4dn-cloud-infra can still be a shared transitive dependency of
  Foursight. The script removes only named top-level distribution roots and their matching
  metadata; it does not remove shared transitive packages.
* The configured Lambda layer is not inspected by this script. A dependency supplied by the
  layer may make a package appear safe to remove, while a layer change may make it required.
  Validate the deployed layer and a representative cold start before adding a removal rule.
* The script validates protected runtime package roots when present and validates the rebuilt zip,
  but it cannot prove runtime reachability. Use ``--dry-run --report`` and a representative
  deployment package as part of release validation.
