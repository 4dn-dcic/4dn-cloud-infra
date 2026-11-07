Human Direct AWS Access Roles
-----------------------------

``C4IAM`` in ``src/parts/iam.py`` optionally creates ``*DevDiagnoseRole`` and
``*PowerRemediateRole``, separate from the unchanged, much broader ``*DevRole``.
Both are **disabled by default**. Neither is emitted without an explicit enable flag
and a nonempty list of approved principals. No new exports or cross-stack dependencies
are introduced; outputs contain generated role names, not credentials.

This is a direct-API permission model, **not a sandbox or an information-flow boundary**.
Review the retained delegation and credential-exposure risks below before enabling it.

A third, independently enabled role, ``*InfraDeployRole``, deploys the stacks themselves; see
`Deployment role`_. The sections before it describe the diagnosis and remediation roles.

Configuration and trust
-----------------------

Set these in ``custom/config.json`` (replace placeholders before use)::

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

Deployment role
---------------

``*InfraDeployRole`` deploys the infrastructure this repository defines: the ``c4-*`` stacks
that ``cli provision <stack>`` synthesizes and the Foursight package ``cli provision foursight*``
builds, through reviewed CloudFormation change sets. It also starts the CodeBuild image builds,
pushes and retags images, runs the ECS release commands ``deploy-ecs`` and ``identity-swap``, and
recovers or deletes failed ``c4-*`` stacks. It is a separate trust decision, so it has
its own switches and never reuses the diagnose/remediate principals::

    "human_access.deploy.enabled": true,
    "human_access.deploy.trusted_principals": "arn:aws:iam::<account-id>:role/<ApprovedDeployers>"

Without both, nothing is added. Trust, MFA, source identity and ``human_access.require_mfa`` /
``human_access.source_identity_pattern`` behave as described above. The session ceiling is one hour.
The role's allows are three customer managed policies created alongside it (the documents exceed a
role's inline-policy quota); its denies are an inline policy. It has no permissions boundary and
does not use the diagnose/remediate boundary, which denies the CloudFormation and IAM writes that
deployment needs. ``tests/test_human_deploy_role.py`` documents every decision below.

Scope and rationale
~~~~~~~~~~~~~~~~~~~

Synthesis (``cli provision <stack>``)
    ``cloudformation:DescribeStacks`` for the exported outputs the templates read.
Change set (``aws cloudformation deploy --no-execute-changeset``)
    ``DescribeStacks``, ``GetTemplateSummary``, ``CreateChangeSet`` on ``c4-*`` stacks and the
    ``Serverless-2016-10-31`` transform (a CloudFormation service role is refused), ``DescribeChangeSet``.
Review and execute
    ``ExecuteChangeSet``, ``DeleteChangeSet``, ``CancelUpdateStack``.
Recover or delete a stack (``aws cloudformation continue-update-rollback``/``rollback-stack``/``delete-stack``)
    ``ContinueUpdateRollback``, ``RollbackStack``, ``DeleteStack`` on ``c4-*`` stacks, with no
    CloudFormation service role. See `Stack deletion, rollback and replacement`_.
Image builds (CodeBuild console or ``aws codebuild start-build``)
    ``StartBuild``, ``StopBuild``, ``BatchGetBuilds``, ``ListBuildsForProject``, ``ListProjects``.
Image push and retag (``docker push``, ``add-image-tag``, ``unrelease-most-recent-image``)
    ``ecr:GetAuthorizationToken``; AWS's documented push set (``BatchCheckLayerAvailability``,
    ``InitiateLayerUpload``, ``UploadLayerPart``, ``CompleteLayerUpload``, ``PutImage``,
    ``BatchGetImage``); ``DescribeImages`` for the retag commands.
ECS redeploy (``deploy-ecs --list`` / ``--kick --env <cluster>``)
    ``ecs:ListClusters``, ``ListServices`` (region-pinned) and ``UpdateService`` with
    ``forceNewDeployment``.
Blue/green swap (``identity-swap <blue> <green> [--mirror] [--do-legacy]``)
    ECS ``ListClusters``/``ListServices``/``ListTaskDefinitions``/``DescribeServices`` and
    ``UpdateService`` (new task definition); Application Auto Scaling ``RegisterScalableTarget``,
    ``PutScalingPolicy``, ``DeleteScalingPolicy`` only for ``ecs`` / ``ecs:service:DesiredCount``
    targets in this account and region, plus ``DescribeScalingPolicies``/``DescribeScalableTargets``
    and the ``ecs.application-autoscaling`` service-linked role; CloudWatch ``DescribeAlarms`` and
    ``PutMetricAlarm`` (already granted for the alarm resources); ``s3:GetObject`` on the global env
    buckets and ``s3:PutObject`` on only the files the command rewrites (below), both limited by
    ``s3:ResourceAccount`` to this account.
Foursight package upload (``aws cloudformation package``/``deploy --s3-bucket``)
    ``s3:PutObject``/``GetObject`` on ``*application-versions`` buckets in this account;
    ``kms:GenerateDataKey``/``Decrypt`` only through S3.
Resources in the templates
    The create/read/update actions each resource type's CloudFormation handler declares, limited
    to the properties these templates set.
Generated identities
    IAM roles, users and instance profiles named ``c4-*``; the four AWS managed policies the
    CodeBuild roles attach; ``iam:PassRole`` of ``c4-*`` roles to ECS tasks, EC2, Lambda and
    CodeBuild; six service-linked roles.

Every CloudFormation handler permission for every resource type in the synthesized templates (plus
the Foursight SAM resources) is either granted or explicitly excluded in the tests, with a reason:
an invalid name in AWS's own handler metadata, a feature the templates never set, a destructive
delete, or identity administration. The handler and action data are official AWS downloads stored
in ``tests/data/aws_iam_deploy_reference.json``.

Resource-authorized actions use account/region service ARNs, as for the other roles. Two
scopes are narrower because the CLI's naming allows it: CloudFormation writes are limited to
``c4-*`` stacks, and IAM writes to ``c4-*`` generated names. Buckets have no account in their ARN, so
bucket configuration applies to any bucket the account can reach; package objects additionally
require ``s3:ResourceAccount``. CodeBuild projects and ECR repositories are named from the
environment name (``<env>``, ``<env>-blue``, ``<env>-pipeline-builder``, ``tibanna-awsf`` and the
pipeline images), not ``c4-``, so builds and image writes cover every project and repository in
the account and region. Inventory/discovery reads and the few actions AWS authorizes only
against ``*`` (``kms:CreateKey``/``TagResource``, ``secretsmanager:GetRandomPassword``, CodeBuild
source credentials, ECS task-definition registration, ``ecr:GetAuthorizationToken``, the ECS and
Application Auto Scaling list/describe calls) are region-pinned. This is a deliberately
small action set for this repository's templates, **not** a proven minimum: the tests are static,
and a property you add later may need a handler permission that was excluded as unused.

Escalation and what the guardrail does and does not stop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Deployment writes IAM roles with arbitrary inline policies and hands them to services that run
code; the Foursight Lambda role (``.chalice/policy-*.json``) is itself very broad. **Anyone who can
deploy can obtain any permission a ``c4-*`` runtime role can be given.** Treat deployers as
account administrators for application resources. The inline guardrail denies:

* changes to, or passing of, this role, ``*DevDiagnoseRole``, ``*PowerRemediateRole``, ``*DevRole``,
  the human-access boundary and the ``InfraDeploy`` policies (generated names are matched by their
  logical-id token; synthesis refuses an IAM stack name long enough to truncate it);
* access keys, login profiles, MFA, identity providers, groups, customer managed policies,
  permissions boundaries, SSO, Organizations, billing, and ``sts:AssumeRole``/``GetFederationToken``;
* running workloads directly: Lambda invocation, ECS run/exec, CodeBuild retries and batch builds,
  Step Functions starts, SSM sessions/commands, image deletion, search-index HTTP and queue message
  APIs;
* data destruction: deletion of RDS instances, OpenSearch/Elasticsearch domains, buckets and
  objects, queues, secrets, KMS keys (and disabling them), ECR repositories, log groups and Redis
  replication groups, whether called directly or by CloudFormation on the role's behalf;
* ``DeleteStack``/``RollbackStack`` on stacks not named ``c4-*``, stack-set deletion, and changes to
  termination protection or stack policies;
* secret writes other than the RDS secret's endpoint attachment, and every secret payload rewrite;
* requests outside the deployment region (global services excepted, as for the other roles).

Deployers can read the ``C4*`` secrets: CloudFormation resolves secret references and runs the
secret resource handlers with the caller's credentials.

ECS release commands and the global env bucket
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``deploy-ecs`` forces a new deployment of every service in a cluster, and ``identity-swap``
re-points the blue and green services to each other's task definitions. Both change what serves
traffic immediately; they start no ad-hoc tasks (``RunTask``/``ExecuteCommand`` stay denied).
``identity-swap`` also deletes and re-creates the indexer services' step-scaling policies and
re-points the queue-depth alarms to them; the role can do that for ECS desired-count targets only.

The env-bucket writes are object-exact. The command switches the live ecosystem by rewriting:

* ``<env>-foursight-envs/main.ecosystem`` - the generated env bucket (``FSBucketTemplate.ENVS``;
  SMaHT's ``smaht-production-foursight-envs``);
* ``foursight-prod-envs/main.ecosystem`` - Fourfront's pre-existing env bucket;
* with Fourfront ``--do-legacy`` only, ``main.ecosystem``, ``data``, ``staging``,
  ``fourfront-production-blue`` and ``fourfront-production-green`` in the legacy ``foursight-envs``.

No other object in those buckets can be written, nothing can be deleted, and object ACLs and bucket
policies are untouched. The bucket names are the command's own constants and naming template, not
configuration this role reads. SMaHT uploads with SSE-KMS (``SMAHT_KMS_KEY_ID``): the role's
S3-only data-key permission covers the IAM side, and the key policy must name the role, which the
datastore key policy does when this role is configured (a pre-existing key needs the onboarding
update in KMS below). ``deploy-ecs`` uses ``us-east-1`` (``ECSUtils.REGION``) and the other
commands the session region, so they work only when that is the role's deployment region.

Builds and images: delegated authority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A build runs as its project's CodeBuild service role, not as the deployer. That role (in the
CodeBuild stack) has ``AWSCodeBuildAdminAccess``, ``AmazonS3FullAccess``,
``AmazonEC2ContainerRegistryPowerUser`` and ``CloudWatchFullAccess``, runs in the VPC in privileged
mode, and clones with the GitHub personal access token. ``StartBuild`` accepts per-build overrides
(buildspec, source and version, image, environment variables, service role), which the repository's
build commands may use and which this role does not restrict; the role can also update the project
itself. A build can therefore do anything the CodeBuild role can, **including deleting S3 objects
and buckets and ECR images that the deployment role's own guardrail denies**. This is the same
trusted-deployer model as above, not a sandbox.

Image pushes and retags (``PutImage``) change what runs: ECS starts the image tag its task
definition names (for example ``latest``/``released``) on its next deployment or task replacement.
Images cannot be deleted by the role; repository policies and image deletion stay administrator
operations.

Stack deletion, rollback and replacement
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CloudFormation performs every resource operation - create, update, replace, roll back, delete -
with the role's session. The role may delete ``c4-*`` stacks, finish (``ContinueUpdateRollback``) or
force (``RollbackStack``) a rollback, and cancel an update. For ECS, EC2, load balancing, network,
IAM roles and instance profiles, CodeBuild, Lambda/API Gateway, alarms and RDS/ElastiCache parameter
and subnet groups, deletes are allowed, so replacement, rollback and stack deletion remove them
normally. Deleting an application stack takes that application offline. CloudFormation refuses to
delete a stack whose exports another stack still imports, so shared stacks go last.

The delete APIs of data-bearing resources stay denied, including when CloudFormation calls them:
RDS instances, OpenSearch/Elasticsearch domains, buckets and objects, queues, secrets, the KMS key
(deletion and disabling), ECR repositories, log groups and Redis replication groups. The S3
federator IAM user is also kept, because deleting its access key is credential administration. The
tests derive this list from AWS's delete-handler permissions. Data retention wins over automatic
cleanup:

* **Stack deletion:** the stack ends in ``DELETE_FAILED`` with those resources still present. Delete
  it again with ``aws cloudformation delete-stack --retain-resources <logical ids>``; the stack is
  then gone and the resources remain, no longer managed by CloudFormation.
* **Failed first creation** (typically the datastore): the rollback cannot delete them, so the stack
  ends in ``ROLLBACK_FAILED``. Delete it as above. A retry that reuses fixed physical names (bucket
  names, the RDS identifier, search domain names, secret names) collides with the retained
  resources until an administrator deletes them or imports them into the new stack. A retained new
  KMS key needs an administrator to schedule its deletion.
* **Replacement or removal in an update:** the new resource is created; the old one's cleanup delete
  fails and it remains.
* **Failed update that created one:** the rollback cannot remove it. Use ``ContinueUpdateRollback``
  with ``--resources-to-skip``, then an administrator removes the orphan.

Successful creates and updates of every supported stack, and deletion of everything except the
resources above, are within the role. Removing retained data-bearing resources is not. As an extra
guard, an administrator can enable termination protection on stacks that must never be deleted
(``aws cloudformation update-termination-protection --enable-termination-protection``); the role
cannot turn it off.

Secrets: initial bootstrap versus ordinary deployment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

CloudFormation owns a secret's whole ``SecretString``. Updating it replaces the payload, wiping
values operators filled in after creation. The deployment role may *create* the application
configuration secret (initial bootstrap, with ``XXX: ENTER VALUE`` placeholders) and the RDS secret
with its generated password and endpoint attachment. It cannot call ``UpdateSecret``, so any later
change set that would rewrite a secret's payload or description fails at that resource and rolls
back, leaving the filled values intact. Filling values (``setup-remaining-secrets``, the console)
and deliberate secret-definition changes are administrator operations outside ordinary deployment.

KMS: identity policy and key policy
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

KMS requires both an IAM permission and a key-policy grant, and the datastore key policy has no
account-root statement (it grants ``kms:*`` only to ``deploying_iam_user``). So when
``human_access.deploy.*`` builds the role, the IAM stack also exports its ARN
(``<IAM stack>-HumanDeployRoleArn``). The datastore template then adds two key-policy statements
naming it:

``Allow the deployment role to create and maintain the key``
    ``DescribeKey``, ``GetKeyPolicy``, ``PutKeyPolicy``, ``GetKeyRotationStatus``,
    ``ListResourceTags``, ``TagResource``, ``UntagResource``, ``UpdateKeyDescription``: what
    CloudFormation's key handlers call. KMS's lockout safety check requires the principal calling
    ``CreateKey``, or replacing the policy later, to hold ``PutKeyPolicy`` under the new policy.
    The template never sets ``BypassPolicyLockoutSafetyCheck``.
``Allow the deployment role to use the key through S3``
    ``GenerateDataKey`` and ``Decrypt`` with ``kms:ViaService`` = ``s3.<region>.amazonaws.com``,
    for SSE-KMS buckets and packaged-artifact uploads/reads.

They grant no deletion, disabling, grants, rotation changes, or direct encrypt/re-encrypt; the IAM
policy also denies deletion and disabling. The ``deploying_iam_user`` and ``Allow use of the key``
statements are unchanged. Without the deploy role, the key policy and every template are byte-for-byte
unchanged.

* **New encrypted datastore:** apply the IAM stack first. The deploy role can then create the
  datastore, because the new key policy names it.
* **Key created before the role existed:** its policy does not name the role, so the role cannot
  add itself. After enabling the role, the key's ``deploying_iam_user`` applies the datastore stack
  once; that administrator remains in the policy, so the update passes the lockout check. Later
  datastore updates can use the role.
* **Removing the role later:** the datastore imports the export. Have the ``deploying_iam_user``
  apply the datastore without ``human_access.deploy.*`` first, then the IAM stack. The role cannot
  remove itself, again because of the lockout check.

``update-kms-policy`` adds Foursight roles to the key's use statement; it does not grant the
deployment role.

Using an existing IAM Identity Center permission set instead
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The same four documents can be attached to an existing permission set: the three allow documents
as IAM customer managed policies in the member account, and the guardrail as the permission set's
inline policy. ``python -m src.commands.render_deploy_policy_bundle`` renders them as plain JSON for
one account and Region (``--check`` verifies an existing bundle). The tracked bundle for
``SMaHT-Deployment-Manager`` in account 517723527581 (us-east-1), with its setup and reprovisioning
guide, is in ``docs/examples/smaht-deployment-manager-517723527581-us-east-1/``.

That path creates no role or trust policy. Authentication and session length stay with Identity
Center, the policies are updated by regenerating them, and the datastore key is reached through
``deploying_iam_user`` rather than the ``HumanDeployRoleArn`` export. Leave ``human_access.deploy.*``
off in that case. The IAM stack (which contains ``*DevRole``) is still applied by an administrator.

Bootstrap (administrator, once)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Set the two ``human_access.deploy.*`` values above, run ``poetry run cli provision iam``, and apply
   the IAM stack with administrator credentials. The deploy role cannot create or change itself.
#. Read the ``C4IAMMain<App>InfraDeployRoleName`` output; the role ARN is
   ``arn:aws:iam::<account-id>:role/<that name>``.
#. Grant each trusted principal ``sts:AssumeRole`` and ``sts:SetSourceIdentity`` on that ARN in its
   own account/permission set.
#. If an encrypted datastore already exists, apply it once as its ``deploying_iam_user`` (see KMS).
#. Optionally enable termination protection on the datastore and IAM stacks.
#. Changes to ``*DevRole``, the human-access roles or their policies remain administrator operations.

Deploying with the role
~~~~~~~~~~~~~~~~~~~~~~~

Assume the role with MFA and a source identity, export the session, and confirm it::

    aws sts assume-role --role-arn arn:aws:iam::<account-id>:role/<deploy role name> \
        --role-session-name <you>-deploy --source-identity <you@example.org> \
        --serial-number <mfa device arn> --token-code <code> --duration-seconds 3600
    export AWS_ACCESS_KEY_ID=<AccessKeyId> AWS_SECRET_ACCESS_KEY=<SecretAccessKey> \
        AWS_SESSION_TOKEN=<SessionToken> AWS_DEFAULT_REGION=<region>
    unset AWS_PROFILE
    aws sts get-caller-identity    # must show assumed-role/<deploy role name>/...

Do not source a ``custom/aws_creds/test_creds.sh`` that exports other keys afterwards. Then, for a
``c4-*`` stack::

    poetry run cli provision <stack>          # no --upload-change-set, no --validate
    # prints: Wrote template to .../out/templates/<stack name>-<timestamp>-<md5>.yml
    poetry run aws cloudformation deploy --no-execute-changeset \
        --template-file out/templates/<file>.yml --stack-name <stack name> --capabilities CAPABILITY_IAM \
        --parameter-overrides NetworkStackNameParameter=<network stack> \
            ECRStackNameParameter=c4-ecr-main-stack IAMStackNameParameter=c4-iam-main-stack \
            LoggingStackNameParameter=c4-logging-main-stack
    aws cloudformation describe-change-set --change-set-name <change set ARN printed above>
    aws cloudformation execute-change-set --change-set-name <change set ARN>

These are the overrides ``--upload-change-set`` passes; ``aws cloudformation deploy`` ignores those
a template does not declare. The network stack is ``c4-network-main-stack`` for every app kind.

For Foursight, package without uploading, then upload and create the change set with the session.
Use the ``*application-versions`` bucket and, when encryption is on, ``s3.encrypt_key_id`` (the
bucket policy rejects uploads without SSE-KMS)::

    poetry run cli provision <foursight stack> --stage prod --output-file out/foursight-prod-tmp/ \
        [--foursight-identity <GAC name>]
    poetry run aws cloudformation package --template-file out/foursight-prod-tmp/sam.yaml \
        --s3-bucket <...-application-versions> --kms-key-id <s3.encrypt_key_id> \
        --output-template-file out/foursight-prod-tmp/sam-packaged.yaml
    poetry run aws cloudformation deploy --no-execute-changeset \
        --template-file out/foursight-prod-tmp/sam-packaged.yaml --stack-name <foursight stack name> \
        --s3-bucket <...-application-versions> --kms-key-id <s3.encrypt_key_id> --capabilities CAPABILITY_IAM

then review and execute the change set as above. A ``foursight.application_version_bucket`` whose
name does not end in ``application-versions`` is outside the role's upload scope.

Builds, image pushes and retags, in the same session::

    aws codebuild start-build --project-name <env>        # or the CodeBuild console
    aws codebuild batch-get-builds --ids <build id>       # status; stop-build --id <build id> cancels
    aws ecr get-login-password | docker login --username AWS --password-stdin <account-id>.dkr.ecr.<region>.amazonaws.com
    docker push <account-id>.dkr.ecr.<region>.amazonaws.com/<repository>:<tag>   # e.g. scripts/upload_tibanna_awsf
    poetry run add-image-tag --account-number <account-id> --ecs-repository <env> <sha256 digest> <tag>
    poetry run unrelease-most-recent-image --account-number <account-id> --ecs-repository <env>

(``add-image-tag``/``unrelease-most-recent-image`` also expect ``ACCOUNT_NUMBER`` in the environment.)
Build logs are in CloudWatch Logs, which this role does not read; use ``*DevDiagnoseRole`` or the
build status.

ECS releases, in the same session (``identity-swap`` reads ``custom/config.json`` for the app kind)::

    poetry run deploy-ecs --list
    poetry run deploy-ecs --kick --env <cluster ARN or name>
    poetry run identity-swap <blue env> <green env>             # SMaHT
    poetry run identity-swap <blue env> <green env> [--mirror]  # Fourfront

Recovering or deleting a ``c4-*`` stack::

    aws cloudformation continue-update-rollback --stack-name <stack> [--resources-to-skip <ids>]
    aws cloudformation rollback-stack --stack-name <stack>      # a failed stack with rollback disabled
    aws cloudformation delete-stack --stack-name <stack>
    aws cloudformation wait stack-delete-complete --stack-name <stack>   # fails on DELETE_FAILED
    aws cloudformation delete-stack --stack-name <stack> --retain-resources <logical ids>

Never pass ``--role-arn``; the role refuses it.

Why not ``--upload-change-set``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``--upload-change-set`` and ``--validate`` run ``amazon/aws-cli`` in Docker with only
``custom/aws_creds`` mounted and no environment forwarded, so they use whatever long-lived
credentials that directory holds, never the assumed-role session. Synthesis itself runs in-process
and uses the environment session. The tests pin both behaviours.

Not covered by the deployment role
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Applying the IAM stack's human-access roles, onboarding a pre-existing datastore key, filling secrets,
``assure-global-env-bucket`` (writes the env bucket), ``update-kms-policy``, ``update-cors-policy``,
``update-sentieon-security``, Tibanna deployment, ECS deployment-task runs (``RunTask``), CodeBuild
retries and batch builds, image deletion, reference-file copies, and removal of the data-bearing
resources retained after a failure or stack deletion. Those need
administrator or runtime credentials. Validate any role
before relying on it: the tests are static, and no live role-based deployment has been run. In
particular, CloudFormation documents that it uses a temporary session generated from the caller's
credentials, but not how that interacts with a role session expiring during a long operation such as
datastore creation; start long change sets early in a fresh session.

Operator checks before use: ``aws iam simulate-principal-policy --policy-source-arn <deploy role ARN>
--action-names cloudformation:CreateChangeSet iam:CreateRole --resource-arns <arns>`` for the
operations you plan, and a first change set on a non-production stack.
