Pruning Chalice deployment packages
===================================

``scripts/prune_chalice_package.sh`` removes known build/provisioning packages from a Chalice
deployment archive after the archive has been built. The existing removal of nested ``test``,
``tests``, and ``examples`` directories is retained. Package removal is an explicit allow-list;
the script does not delete files based on static-import analysis.

The original one-argument invocation remains supported::

    scripts/prune_chalice_package.sh path/to/deployment.zip

Use ``--dry-run --report`` to inspect the proposed removals without changing the archive. Use
``--variant cgap``, ``--variant fourfront``, or ``--variant smaht`` only when the archive is known
to contain the selected ``chalicelib_*`` implementation. A variant removes the other
``chalicelib_*`` roots; without a variant, all application variants are retained for compatibility
with the runtime selection in ``app.py``.

The ``chalice`` and ``tibanna`` runtime roots, including their distribution metadata, are kept.
The current package-removal allow-list is limited to ``awacs`` and ``troposphere``; extend it only
after confirming the package is not needed by either deployed Foursight variant.

Runtime-risk assumptions
-------------------------

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
