Chalice package pruning controls
=================================

Foursight provisioning keeps its historical pruning behavior by default. The optional
``provision`` controls below are useful when investigating package contents::

    poetry run cli provision foursight --prune-dry-run --prune-report \
        --prune-variant cgap

``--prune-dry-run`` asks foursight-core to inspect the generated package without
replacing ``deployment.zip``. It also prevents package upload and CloudFormation
change-set creation, even if ``--upload-change-set`` was supplied. Use
``--prune-report`` for one line per removal candidate. ``--prune-variant`` accepts
``all``, ``cgap``, ``fourfront``, or ``smaht``; selecting a variant permits the
packager to remove the other application roots. ``--no-prune`` bypasses pruning
entirely for troubleshooting. Dry-run and no-prune are mutually exclusive.

The cloud-infra/foursight-core integration uses an explicit ``prune_options`` keyword
argument. Cloud-infra passes it only when one of these controls is selected, so older
invocations retain the existing call shape and defaults. The compatible contract is a
mapping with these keys:

* ``enabled`` (boolean): false bypasses pruning;
* ``dry_run`` (boolean): inspect and report without changing the archive;
* ``report`` (boolean): emit detailed removal reporting; and
* ``variant`` (string): ``all``, ``cgap``, ``fourfront``, or ``smaht``.

Foursight-core is responsible for applying these options to its Chalice packaging
implementation and for leaving ``deployment.zip`` unchanged in dry-run mode. The
currently locked foursight-core release predates this optional keyword; install the
compatible foursight-core change before using these flags. No environment variable
fallback is used.

For the package-level rules and runtime safety assumptions, see the corresponding
``scripts/prune_chalice_package.sh`` documentation when that implementation is
available.
