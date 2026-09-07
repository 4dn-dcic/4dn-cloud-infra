Human Direct AWS Access Roles
-----------------------------

``C4IAM`` in ``src/parts/iam.py`` optionally creates ``*DevDiagnoseRole`` and
``*PowerRemediateRole``, separate from the unchanged, much broader ``*DevRole``.
Both are **disabled by default**. Neither is emitted without an explicit enable flag
and a nonempty list of approved principals. No new exports or cross-stack dependencies
are introduced; outputs contain generated role names, not credentials.

This is a direct-API permission model, **not a sandbox or an information-flow boundary**.
Review the retained delegation and credential-exposure risks below before enabling it.

Configuration and trust
-----------------------

Set these in ``template.config.json`` (replace placeholders before use)::

    "human_access.diagnose.enabled": true,
    "human_access.diagnose.trusted_principals": "arn:aws:iam::<account-id>:user/alice",
    "human_access.remediate.enabled": true,
    "human_access.remediate.trusted_principals": "arn:aws:iam::<account-id>:role/ApprovedOperators"

Principal lists accept comma/newline-separated strings or JSON arrays of concrete
commercial-AWS IAM user/role ARNs. Account IDs, root, wildcards, service principals,
STS session ARNs and malformed entries are rejected at synthesis. Generated trust policies
must fit IAM's default 2048-character quota; this feature does not raise quotas. Identity Center role
paths are supported. Cross-account trust is permitted only for an explicitly named
principal; that caller also needs authorization in its own account. The policies use
``arn:aws`` and are not a GovCloud/China partition implementation.

``human_access.require_mfa`` (default ``true``)
    The trust policy requires MFA and ``aws:MultiFactorAuthAge < 3600`` when assuming
    either role. **MFA is enforced at assumption, not per downstream API call**:
    AssumeRole credentials do not carry MFA context for those checks. Adding a Bool
    MFA condition to remediation permissions would make ordinary assumed-role calls fail.
    Set this switch to ``false`` only when the identity provider enforces MFA upstream
    (for example, Identity Center). This switch covers both roles and all their principals;
    do not include callers lacking upstream MFA. Leaving it on for incompatible federation fails closed.

``human_access.source_identity_pattern`` (optional)
    Restricts ``sts:SourceIdentity`` with StringLike, for example ``*@hms.harvard.edu``.
    Source identity is always required; callers need ``sts:SetSourceIdentity`` and must
    supply or propagate it. A manually supplied label is **not verified identity** and an
    email-pattern check does not prove ownership of that email. Correlate it with the
    authenticated caller in CloudTrail, or enforce a trusted IdP mapping upstream.

Both roles have a **one-hour enforceable ceiling** (``MaxSessionDuration=3600``), the
minimum IAM supports. Request ``DurationSeconds=1800`` for remediation, but this is
**not an enforced 30-minute ceiling**; a caller can request 3600. There is no
``sts:DurationSeconds`` IAM condition key and no external session broker in this design.

Actions, resources and boundaries
---------------------------------

The action allowlists are explicit: neither role grants ``Action: *`` or ``service:*``.
Resources are service-level, not individually enumerated. Remediation covers **every**
ECS service/task, queue, state machine/execution and CodeBuild project in this account
and deployment region, including production and both sides of a blue/green pair.

Resource-authorized inspection (including ECS services/tasks/clusters, stack descriptions,
log streams, RDS instances and OpenSearch domains) uses account/region service ARNs.
The remaining discovery/inspection groups use ``Resource: *`` with ``aws:RequestedRegion``
and ``aws:ResourceAccount`` when AWS supplies that context. Inventory requests often do
not supply a resource owner: a region condition alone is not an account boundary.
These groups include, for example, list APIs, task-definition inspection, metrics,
composite-alarm inspection and cancellation of Logs Insights queries. They must not be
mistaken for proof that every Describe/List API is unscopable.

S3 ARNs have no account component. S3 reads require ``s3:ResourceAccount`` to match this
account, with explicit cross-account denies in the diagnostic policy and shared boundary.
Consequently even a bucket policy granting a human role session access cannot authorize
reads of another account's buckets. This also excludes AWS-owned service buckets.

The permission boundary is a **ceiling, not a grant**. Its Allow-all statement enables
intersection with the role's explicit grants; the denies block direct identity, network,
CloudFormation, code-authoring and destructive data APIs. It is defense in depth, not an
exhaustive denylist for all future AWS APIs. Never attach additional policies on the
assumption that the boundary alone defines this role's complete action allowlist.
Global-service exceptions in the region deny are not grants. Keep direct PassRole,
AssumeRole and GetFederationToken denied; use a fresh assume from the approved human
identity to switch roles. The original DevRole is not retired by this feature.

Retained risks: approve before enabling
---------------------------------------

* **Diagnostic reads expose sensitive information.** S3 objects, Secrets Manager values,
  application logs, CloudFormation templates, build metadata, workflow histories and
  Lambda inventory can contain data, credentials or configuration. Denying direct
  ``lambda:GetFunctionConfiguration`` does not remove configuration returned by
  ``lambda:ListFunctions``. Credential material copied from a secret can be used outside
  this role; its boundary cannot constrain the separate identity. Treat diagnosis as
  trusted access to all readable account data, not as a low-trust support role.
* **CodeBuild delegation is intentionally retained.** ``codebuild:StartBuild`` accepts
  ``buildspecOverride``, source/image/environment overrides and ``sourceVersion`` under
  the existing project service role. It can execute arbitrary build commands, publish
  images, read secrets or mutate resources permitted to that service role, even though
  the human is denied the corresponding direct APIs and ``iam:PassRole``. ``RetryBuild``
  can repeat a previously overridden build. The project repository/branch is not pinned
  against request overrides. No no-override restriction or new broker is provided here.
* ``states:StartExecution`` accepts caller-controlled input. Existing state machines can
  perform code execution, data writes or destructive operations under their service roles.
  Neither the human boundary nor a direct API deny propagates to those roles. Starting
  or stopping workflows/builds/tasks is **not guaranteed reversible**.
* ``ecs:UpdateService`` is broader than restart/rescale: this policy does not constrain
  its task-definition, network or other supported request fields. Existing images/task
  definitions and service-linked roles can change what runs or its exposure. Direct
  ``ec2`` perimeter denies are not a restriction on delegated ECS service operations.
* Queue purge/deletion/message receipt remain denied. ``ChangeMessageVisibility`` requires
  an already-held valid receipt handle; it cannot discover/release arbitrary in-flight
  messages while ``ReceiveMessage`` is denied. Do not promise a general queue-unblocking API.

Before enabling remediation, review **all** reachable CodeBuild projects, workflow input
contracts, ECS services, their execution roles and mutable images. Approve their delegated
privileges, require upstream change controls, and monitor CloudTrail for overrides,
execution inputs and ECS configuration changes. Region pins restrict requests, not all
cross-region effects that a delegated service role might cause.

KMS opt-in
----------

``human_access.diagnose.allow_kms_decrypt`` defaults to ``false``. Decrypt is explicitly
denied by default; key metadata remains readable. Enabling adds ``kms:Decrypt`` and
``kms:GetKeyPolicy`` for all keys in this account/region, allowing supported encrypted
S3 objects **and Secrets Manager secrets** to be read when otherwise authorized.

KMS key policy authorization is also required, but the key policy need not explicitly
name this role: a default account-root statement can already delegate authorization to
IAM. **The switch may grant decrypt immediately without any key-policy change.** Inspect
existing key policies/grants before opting in. Do not change key policies merely to make
an expected AccessDenied disappear; this template makes no key-policy changes.

Offline verification
--------------------

``tests/test_human_access_roles.py`` and ``tests/test_human_access_regressions.py`` check
opt-in parity, malformed trust, action/deny intersections, owner conditions, references,
IAM quotas, session limits and full README example parity (actions, resources, conditions).
They synthesize templates; they are not an AWS IAM simulator or evidence of deployment.
Use the mock config from ``.github/workflows/main.yml`` and locked dependencies for tests.
Run ``pytest tests src/tests`` and local ``cfn-lint`` on synthesized templates without AWS
credentials/network access. **Do not use ``make alpha`` for offline validation**: it invokes
CloudFormation validation against AWS. No infrastructure is applied by these tests.
