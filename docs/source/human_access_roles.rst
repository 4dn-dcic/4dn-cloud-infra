Human Direct AWS Access Roles
-----------------------------

Two optional IAM roles let people work directly in AWS without assuming ``*DevRole``
(which is trusted by the account root and carries ten full-access managed policies):

``*DevDiagnoseRole``
    Read-only diagnosis. The read/inspection actions needed to answer "is it up, why did that
    task die, is indexing backed up", plus Secrets Manager and S3 object reads so a developer can
    inspect the system and bring evidence to a change request.

``*PowerRemediateRole``
    The reversible operational actions needed to remediate those same services: restart or
    rescale a service, stop a stuck task, release in-flight queue messages, start or stop a
    workflow execution, trigger a CI rebuild.

Both are built by ``C4IAM`` in ``src/parts/iam.py`` and live in the IAM stack. The README has
illustrative JSON for each role, which is useful for review; ``src/parts/iam.py`` is the only
authoritative source.

Scoping model
-------------

This account holds only our own resources, so these policies **do not enumerate resource
identifiers**. Two rules apply instead:

* Where an action supports resource-level authorization, the resource is scoped to the **service** -
  ``arn:aws:ecs:<region>:<account>:service/*``, ``arn:aws:s3:::*/*``,
  ``arn:aws:secretsmanager:<region>:<account>:secret:*`` and so on. Every resource of that type in
  this account and region, and nothing outside it.
* Where an action has no resource-level authorization at all (``ecs:Describe*``,
  ``cloudwatch:GetMetricData``, ``ec2:Describe*``, ``sqs:ListQueues``, ``sts:GetCallerIdentity``),
  AWS accepts only ``"*"``. Those actions live in one named read-only statement per role and are
  constrained by an ``aws:RequestedRegion`` condition instead.

The constraint that carries the weight is therefore **the action list**, which is fully enumerated.
Neither role grants ``"Action": "*"`` or a service-wide wildcard such as ``ecs:*``.

Consequence worth being explicit about: because remediation is scoped at the service level, it
reaches **every** ECS service, queue, state machine and CodeBuild project in the account -
including the live side of a blue/green pair. The controls that bound it are the short action list
(all reversible), the MFA-gated short session, the region pin, and the fact that the role is
disabled by default and assumable only by enumerated principals.

Both roles also carry a permission boundary. A boundary is a **ceiling, not a grant**: effective
permissions are the intersection of the role's own policies and the boundary, so it must open with
an ``Allow`` or the roles could do nothing. It does not widen either role; it is a backstop so that
a future additive edit still cannot reach identity administration, CloudFormation mutation, the
network perimeter, the image supply chain, or data-plane writes.

Nothing is created by default
-----------------------------

With none of the ``human_access.*`` settings in ``template.config.json``, the IAM template is
byte-for-byte what it was before - no roles, no boundary, no CloudFormation parameters or
conditions. Enabling any of this is always deliberate.

A role is also **not** created when it is enabled but no approved principal ARNs were supplied.
There is no account-root trust fallback: that is the exact weakness these roles exist to avoid.

Configuration
-------------

Because resources are scoped at the service level, there is nothing to configure per resource. The
only settings are who may assume each role, the trust conditions, and one explicit opt-in.

Turn a role on and say who may assume it. Principal lists are comma-separated::

    "human_access.diagnose.enabled": true,
    "human_access.diagnose.trusted_principals": "arn:aws:iam::<acct>:user/alice, arn:aws:iam::<acct>:user/bob",

    "human_access.remediate.enabled": true,
    "human_access.remediate.trusted_principals": "arn:aws:iam::<acct>:user/alice"

Trust conditions:

``human_access.require_mfa`` (default ``true``)
    Asserts ``aws:MultiFactorAuthPresent`` on assume and on every remediation action. Set it to
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

The one capability opt-in:

``human_access.diagnose.allow_kms_decrypt`` (default ``false``)
    Adds ``kms:Decrypt`` and ``kms:GetKeyPolicy`` for the diagnostic role, needed to read objects in
    an SSE-KMS bucket. It is off by default because at service scope it reaches any key in the
    account. Plain key metadata (``kms:DescribeKey``, ``kms:GetKeyRotationStatus``,
    ``kms:ListAliases``) is always available, so bucket encryption stays diagnosable without it.

    **KMS requires dual authorization.** This setting alone grants nothing: the key policy must
    also name the role. That is a separate, out-of-band change (see ``encryption.rst`` and
    ``update-kms-policy``). Until it is made, S3 object reads on an encrypted bucket return
    ``AccessDenied``, which looks like a bug but is not.

What these roles deliberately cannot do
---------------------------------------

Neither role can push an image (``ecr:PutImage``), register a task definition, run a task, open a
shell in a container (``ecs:ExecuteCommand``), update Lambda code, pass a role, mutate
CloudFormation, change the network perimeter, administer IAM or Identity Center, write to S3 or RDS,
or assume another role. ``sts:AssumeRole`` is denied so neither can be used as a stepping stone -
each privilege increase has to be a fresh, separately audited assume from the person's own identity.

Irreversible queue operations - ``sqs:PurgeQueue`` and ``sqs:DeleteQueue`` - are excluded from
remediation entirely and denied both on the role and in the boundary. There is no switch to enable
them; releasing in-flight messages with ``sqs:ChangeMessageVisibility`` is the reversible
alternative that is granted.

The diagnostic role additionally cannot read SQS message bodies, RDS log files, SSM parameters, or
Lambda function configuration and code, all of which are data or configuration exfiltration paths.

One residual risk is worth stating plainly: IAM has no condition key for the task-definition
argument of ``ecs:UpdateService``, so a remediation holder can repoint a service at another
already-registered task-definition revision. That cannot be expressed in IAM. It is bounded by
``ecr:PutImage`` being denied (no new image content can be authored) and by CloudTrail attribution
under a short MFA-gated session. Alerting on ``ecs:UpdateService`` events whose ``taskDefinition``
differs from the service's prior value is the right complementary control.

Verifying before you rely on it
-------------------------------

``tests/test_human_access_roles.py`` pins the disabled-by-default behaviour, the trust
restrictions, the service-level resource scope, the constrained action lists, the prohibition on
broad administration, and the alignment of the README examples with what the template renders.
Against a real account, ``aws iam simulate-custom-policy`` on the rendered policy documents is the
cheapest way to confirm a specific action is allowed or denied before anyone depends on it.
