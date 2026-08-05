Human Direct AWS Access Roles
-----------------------------

Two optional IAM roles let people work directly in AWS without assuming ``*DevRole``
(which is trusted by the account root and carries ten full-access managed policies):

``*DevDiagnoseRole``
    Read-only diagnosis. The observability reads needed to answer "is it up, why did that
    task die, is indexing backed up", plus **resource-scoped** Secrets Manager and S3 object
    reads so a developer can inspect the system and bring evidence to a change request.

``*PowerRemediateRole``
    A small set of named, reversible operational writes - restart or rescale a service, stop a
    stuck task, release in-flight queue messages, rerun a workflow, trigger a CI rebuild.

Both are built by ``C4IAM`` in ``src/parts/iam.py`` and live in the IAM stack. They share a
permission boundary that forbids identity administration, CloudFormation mutation, network
perimeter changes, supply-chain writes and data-plane writes regardless of what their own
policies say.

Nothing is created by default
-----------------------------

With none of the ``human_access.*`` settings in ``template.config.json``, the IAM template is
byte-for-byte what it was before - no roles, no boundary, no CloudFormation parameters or
conditions. Enabling any of this is always deliberate.

A role is also **not** created when it is enabled but no approved principal ARNs were supplied.
There is no account-root trust fallback: that is the exact weakness these roles exist to avoid.

Configuration
-------------

Turn a role on, and say who may assume it. Principal lists are comma-separated::

    "human_access.diagnose.enabled": true,
    "human_access.diagnose.trusted_principals": "arn:aws:iam::<acct>:user/alice, arn:aws:iam::<acct>:user/bob",

    "human_access.remediate.enabled": true,
    "human_access.remediate.trusted_principals": "arn:aws:iam::<acct>:user/alice"

Trust conditions:

``human_access.require_mfa`` (default ``true``)
    Asserts ``aws:MultiFactorAuthPresent`` on assume and on every remediation write. Set it to
    ``false`` **only** in an IAM Identity Center (SSO) account, where MFA is asserted upstream at
    the identity provider and this condition key cannot be relied on. Leaving it on in an SSO
    account fails closed (the role becomes unassumable), not open.

``human_access.source_identity_pattern`` (optional)
    A ``StringLike`` pattern for ``sts:SourceIdentity``, e.g. ``*@hms.harvard.edu``. Independent of
    this setting, an assume with **no** source identity is always refused, so every session is
    attributable to a person in CloudTrail. Callers must therefore pass
    ``--source-identity <you>`` to ``aws sts assume-role``.

Session length is capped by ``MaxSessionDuration`` on the role itself - one hour for diagnosis,
thirty minutes for remediation. There is no ``sts:DurationSeconds`` condition key.

Diagnostic reads
----------------

``human_access.diagnose.buckets`` (optional)
    Buckets whose objects may be read. Defaults to this deployment's own derived application and
    foursight buckets. Supply an explicit list where bucket names are legacy and do not follow the
    derived ``{env_name}-application-*`` / ``{env_name}-foursight-*`` pattern - some environments
    have pre-orchestration names such as ``foursight-prod-envs``, and a derived list will silently
    miss them.

Secrets are scoped to this deployment's application configuration (GAC) and RDS master secret,
using the names from ``src/names.py``. Log reads are scoped to the logging stack's log groups and
the RDS instance's log groups; those ARNs are prefix wildcards because the log groups are created
without an explicit ``LogGroupName`` and so get CloudFormation-generated physical names.

``human_access.diagnose.allow_kms_decrypt`` (default ``false``)
    Grants ``kms:Decrypt`` on the single key named by ``s3.encrypt_key_id`` - nothing else, and
    never a wildcard. Needed to read objects in an SSE-KMS bucket.

    **KMS requires dual authorization.** This setting alone grants nothing: the key policy must
    also name the role. That is a separate, out-of-band change (see ``encryption.rst`` and
    ``update-kms-policy``). Until it is made, S3 object reads on an encrypted bucket return
    ``AccessDenied``, which looks like a bug but is not.

Remediation targets
-------------------

Every mutating statement is driven by explicitly supplied resource ARNs. An empty list means the
capability is simply absent - nothing falls back to a derived name, to ``ENCODED_ENV_NAME``, or to
a wildcard. Enabling the role without any of these produces a read-only role.

This is deliberate, and it is how a live environment is kept out of scope: in the 4DN account the
blue and green halves of the deployment share one account, so scope is expressed by naming ARNs,
not by relying on an account boundary. **Supply the non-live side's ARNs only.**

::

    "human_access.remediate.service_arns":        "arn:aws:ecs:us-east-1:<acct>:service/<cluster>/<service>",
    "human_access.remediate.cluster_arns":        "arn:aws:ecs:us-east-1:<acct>:cluster/<cluster>",
    "human_access.remediate.queue_arns":          "arn:aws:sqs:us-east-1:<acct>:<env>-indexer",
    "human_access.remediate.state_machine_arns":  "arn:aws:states:us-east-1:<acct>:stateMachine:tibanna_unicorn",
    "human_access.remediate.codebuild_project_arns": "arn:aws:codebuild:us-east-1:<acct>:project/<project>"

``service_arns`` grants ``ecs:UpdateService``; ``cluster_arns`` grants ``ecs:StopTask`` on tasks in
that cluster; ``queue_arns`` grants ``sqs:ChangeMessageVisibility``; ``state_machine_arns`` grants
``states:StartExecution`` / ``StopExecution``; ``codebuild_project_arns`` grants
``codebuild:StartBuild`` / ``StopBuild`` / ``RetryBuild``.

All five settings take **full ARNs, not names**. Two of them are also used to derive a second ARN:
the ``ecs:StopTask`` resource is derived from each cluster ARN (``:cluster/X`` becomes
``:task/X/*``), and the ``states:StopExecution`` resource from each state machine ARN
(``:stateMachine:X`` becomes ``:execution:X:*``). A malformed ARN therefore yields a resource that
matches nothing - the capability fails closed rather than over-granting, but it also will not work.

These ARNs cannot be derived from the templates. ECS clusters and services are created without
``ClusterName`` / ``ServiceName``, so their physical names are CloudFormation-generated - read the
real ARNs out of the account (``aws ecs list-services --cluster <cluster>``) rather than composing
them by hand. Note also that if the account has not opted into the long ECS ARN format, live
service ARNs have no cluster segment and a long-form ARN here would match nothing and fail closed.

``human_access.remediate.allow_queue_purge`` (default ``false``)
    Adds ``sqs:PurgeQueue`` on the supplied queues. This is **irreversible** - purged messages are
    gone - so it is its own explicit choice on top of having supplied queue ARNs at all.

What these roles deliberately cannot do
---------------------------------------

Neither role can push an image (``ecr:PutImage``), register a task definition, run a task, open a
shell in a container (``ecs:ExecuteCommand``), pass a role, mutate CloudFormation, change the
network perimeter, administer IAM or Identity Center, write to S3 or RDS, or assume another role.
``sts:AssumeRole`` is denied so neither can be used as a stepping stone - each privilege increase
has to be a fresh, separately audited assume from the person's own identity.

The diagnostic role additionally cannot read SQS message bodies, RDS log files, SSM parameters, or
Lambda function configuration and code, all of which are data or configuration exfiltration paths.

One residual risk is worth stating plainly: IAM has no condition key for the task-definition
argument of ``ecs:UpdateService``, so a remediation holder can repoint a named service at another
already-registered task-definition revision. That cannot be expressed in IAM. It is bounded by
``ecr:PutImage`` being denied (no new image content can be authored) and by CloudTrail attribution
under a short MFA-gated session. Alerting on ``ecs:UpdateService`` events whose ``taskDefinition``
differs from the service's prior value is the right complementary control.

Verifying before you rely on it
-------------------------------

``tests/test_human_access_roles.py`` pins the disabled-by-default behaviour, the trust
restrictions, the approved diagnostic reads and the denied privileges. Against a real account,
``aws iam simulate-custom-policy`` on the rendered policy documents is the cheapest way to confirm
a specific action is allowed or denied before anyone depends on it.
