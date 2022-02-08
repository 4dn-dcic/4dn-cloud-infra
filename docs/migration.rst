######################
Migration of CGAP Data
######################

It might be useful to fully orchestrate a partial or entire copy
of the CGAP infrastructure. This procedure is relatively straightforward
in the new infrastructure. Each of the following sections will document how
to transfer various bits of data to create an exact replica of the site, in case
further migration or major restructuring needs to occur.

These instructions assume you have already orchestrated the resources for
the new target account.


===
RDS
===

The metadata backing the portal including cases, variants, genes, notes etc are
all stored in the RDS database (datastore.py). Manual database snapshots can
be made available for restore by other AWS accounts. Select a manual snapshot
from the RDS console, or create a new manual snapshot from an existing automated
snapshot and `modify the permissions to allow the restore <https://aws.amazon.com/premiumsupport/knowledge-center/rds-snapshots-share-account/>`_.

In the new target AWS account, navigate to RDS and restore the newly available
snapshot. Once online, update the RDS credentials in the GAC, trigger the
ECS deployment check from Foursight (to swap in the new database), then run the
ECS deployment task from the ECS console (to trigger a reindexing).

Depending on the target accounts resource allocation for the RDS/ES/ECS, it may
take some time for the (potentially larger) database to index. Once you are
satisfied with the metadata state, you can begin closing down resources from
the source account.

==
S3
==

There is a significant amount of S3 data stored in buckets that must be transferred.
The data that is most critical exist in the application layer buckets. The system
bucket we can ignore, as that bucket does not get migrated. The remaining files,
wfoutput and blob buckets all must be transferred into the new buckets.

The simplest way to transfer is to use the ``sync`` API::

    aws s3 sync s3://elasticbeanstalk-fourfront-cgap-wfoutput s3://cgap-mgb-main-application-cgap-mgb-wfoutput

If you are migrating into an encrypted environment, be sure to pass encryption
arguments to the command::

    aws s3 sync s3://elasticbeanstalk-fourfront-cgap-wfoutput s3://cgap-mgb-main-application-cgap-mgb-wfoutput --sse aws:kms --sse-kms-key-id $S3_ENCRYPT_KEY_ID

Pipe this command into a file to get a record of the transfer. Note additionally
that files that are stored in Glacier will NOT be transferred and will be ignored.
Be wary of this when deleting the files from the source account. Foursight and
Tibanna run data is kept in the old account only for historical purposes and
should be deleted after some time. New metadata for future runs will be created
in the new account.

=====================
Functional Validation
=====================

Use the following checklist to validate a large chunk of standard functionality for
the portal. If you encounter issues (internal server error, client side error etc), double
check the application code (cgap-portal or fourfront). Note that this checklist assumes
sufficient production data for various modules to be available.

1. Main Page
    a. Core project searches load within ~5 seconds
    b. q= searches work
    c. Facets work (term, range, SAYT)
    d. Project selection works
2. Submission (Ingestion, Indexing)
    a. Submit gene list works
    b. Submit xls works
3. General Case navigation
    a. Case page loads
    b. Pedigree loads
    c. Patient info loads
    e. Family info loads
    f. Status overview bar loads
    g. Accessioning tab filled out
    h. Bioinformatics tab
    i. Link to QC reports should work
    j. Link to wfoutput files should work
4. Filtering tab
    a. Add facets to filter sets
    b. Name, save filter sets
    c. Saved filter set results persist on reload
    d. Can save VS's to interpretation space
5. Interpretation tab
    a. VS's moved successfully to this module
    b. Classifications can be made, are visible
    c. Gene, transcript links
6. Case review tab
    a. Report generation
7. Variant Sample/Structural Variant Sample View
    a. Variant opens first, fields/links present
    b. Gene info present
    c. Sample info present
    d. Annotation browser loads all tracks
    e. BAM file browser loads all tracks
    f. Bamsnap image links work
