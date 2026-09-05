Shared IAM resource inventory
=============================

The IAM stack (normally ``c4-iam-main-stack``), ECS role, and S3 federator are
**ecosystem-shared**, not environment-scoped. Updating IAM while provisioning a
second environment must not remove the first environment's permissions.

Required before creating or updating IAM
----------------------------------------

Set ``iam.ecosystem_resources`` in ``custom/config.json`` to the **complete union**
of physical resources needed by every consumer of that shared identity. Keep the
same inventory in every environment's configuration. Missing, partial-schema,
wildcard, or malformed inventories fail synthesis; there is no fallback to only
``ENCODED_ENV_NAME`` and no account-wide data-resource fallback.

The value is an object with these six required lists (names, not ARNs):

* ``buckets``: exact application, Foursight, ecosystem, and legacy bucket names.
  Take ``BucketName`` from datastore templates and include existing buckets used
  by each GAC. Do not assume all legacy/shared buckets start with the current env.
* ``queues``: exact ``QueueName`` values, including indexing, secondary, DLQ,
  ingestion and realtime queues, plus any existing queues required by a consumer.
* ``search_domains``: exact ``DomainName`` values. Standard/SRCE use ``os-``;
  Fourfront slim uses ``es-``. Include both blue and green when applicable.
* ``repositories``: exact ``RepositoryName`` values from each ECR template,
  including each portal repository and required fixed pipeline/sidecar repositories.
* ``runtime_secrets``: exact portal GAC/blue/green identity names and Falcon CID
  names. Include the legacy ``fourfront-mastertest`` identity when still consumed.
  Standard RDS secrets start with ``C4Datastore``; SRCE RDS secrets start with
  ``C4SRCEDatastore``. Include them only if a runtime consumer actually reads them
  (portal credentials copied into its GAC do not require direct RDS-secret access).
  Do **not** include Falcon API ClientID/ClientSecret or DockerHub build credentials.
  Only AWS's six-character secret ARN suffix is wildcarded by the generated policy.
* ``kms_keys``: the exact UUID or ``mrk-`` key IDs needed by all consumers, including
  existing external keys. The local ``s3.encrypt_key_id`` alone is **not** the shared
  inventory. An explicit empty list emits no identity KMS grant: bootstrap keys
  created by datastore grant the ECS role and S3 federator directly in their key
  policies. External key policies/grants must be confirmed separately.

For illustration only, a deliberately small two-consumer inventory looks like::

    "iam.ecosystem_resources": {
        "buckets": ["cgap-one-files", "legacy-fourfront-files"],
        "queues": ["cgap-one-indexer-queue", "fourfront-mastertest-indexer-queue"],
        "search_domains": ["os-cgap-one", "es-fourfront-mastertest"],
        "repositories": ["cgap-one", "fourfront-mastertest", "falcon-sensor"],
        "runtime_secrets": ["C4AppConfigCgapOne", "C4AppConfigCgapOneFalconCID", "fourfront-mastertest"],
        "kms_keys": ["11111111-1111-1111-1111-111111111111"]
    }

This example is **not a deployable inventory**. Populate all six lists from your
actual generated templates and approved existing-resource inventory. Template
synthesis is offline; it cannot discover other deployed consumers or prove that
an operator omitted none. Never delete another environment's entries just because
that environment is not being provisioned now. Resource grants are emitted as up to
six customer-managed policies attached to the existing ECS role; S3 and KMS policies
are also attached to the existing federator. This avoids overflowing the role/user
aggregate inline limits merely by enumerating multiple consumers. No IAM identity
is replaced. The developer role retains its existing policy layout and attachments.
Managed-policy size and attachment limits still apply; large ecosystems may require
a separately planned policy split. The regression inventory covers all three app
kinds, standard/SRCE/slim resources and both deployment paradigms within default
policy-size and attachment quotas.

Migration, verification and rollback
------------------------------------

#. Save the previous IAM template and the complete current consumer inventory.
   Synthesize datastore/appconfig/ECR templates for every environment and deployment
   variant; reconcile their physical names with existing GACs and deployed resources.
#. Add the inventory before synthesizing IAM. Review its exact grants, especially
   legacy identities, blue/green domains and externally encrypted buckets. Existing
   roles, users, stack names and exports are retained; no identity replacement is
   necessary for this correction.
#. Compare old and new policies for **every** consumer. Offline tests prove that
   changing the current environment with an unchanged inventory produces identical
   IAM, and that unrelated same-prefix resources/Falcon API credentials are denied.
   They do not prove live key policies, SCPs, boundaries or resource existence.
#. Update the shared inventory additively before adding consumers; remove entries
   only after all consumers are retired. Roll back using the previous *complete*
   inventory/template, not a single environment's earlier configuration. Do not
   roll back to the former broad secret prefix merely to troubleshoot a missing name.

CodeBuild credentials and network
---------------------------------

CodeBuild projects now attach their own generated role (blue/green portal projects
share the portal build role). All current builders opt into DockerHub credentials;
only the first-party pipeline builder opts into Falcon API credentials. The
third-party external pipeline, portal and Tibanna roles cannot read Falcon secrets.
ECS runtime inventory grants CID only, never Falcon API build credentials. Confirm
the upstream first-party buildspec/image contract before running a sensor build.

When ``vpc.id`` is set, the existing ``codebuild`` stack imports VPC, private subnet
and ApplicationSecurityGroup from ``srce-network``. The Application private subnet
list must be present and disjoint from DB/Compute subnets. Without ``vpc.id``, the
standard network imports are unchanged. No new CodeBuild stack or replacement VPC
is created. Deploy the selected network, appconfig and shared-secrets exports first.
