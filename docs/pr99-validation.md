# PR 99 validation evidence

## Failed-check cause

The failed [run 31021769696](https://github.com/4dn-dcic/4dn-cloud-infra/actions/runs/31021769696),
job `92359991100` (“Validate 4dn-cloud-infra stacks build successfully”), tested head
`d1e80ab008c2e3072e54546738f64fd159123e0a`: **2 failed, 110 passed**.
The failures were the two overwrite/no-overwrite tests in `test_setup_remaining_secrets.py`.

The live source was verified before branching. Its merge base was
`d9c9e65c799e1e24f56c6e6fdc5aeed1df9ba68e`. Although the PR API still reported that base SHA,
current `master` was `662443ddb60067180e833b9e6630f26edef0cb73`, whose
[run 33987067164](https://github.com/4dn-dcic/4dn-cloud-infra/actions/runs/33987067164)
passed all 32 tests. That current base is incorporated with a merge, preserving history.

### Controlled comparison

Independent git archives were tested in one isolated Python 3.10.20 environment installed
from the unchanged `poetry.lock`, using the workflow's dummy configuration. Both CI runs
installed dcicutils 8.17.0, boto3 1.36.16 and pytest 7.4.4; the passing CI used Python 3.10.21.
There is no lockfile/workflow change in the original PR that explains the failures.

| Source | Full `tests src/tests` result |
|---|---|
| Exact PR head `d1e80ab` | 2 failed, 110 passed |
| Merge base `d9c9e65` | Same 2 failed, 27 passed |
| Current base `662443d` | 32 passed |
| Exact PR head, replacing **only** the stale secrets test fixture with the current-base file | 112 passed |

The failing file alone gave **2 failed, 1 passed** on both original head and merge base,
and **3 passed** on current base. Conversely, restoring only the stale fixture on current
base reproduced the same two failures. Thus role-test import order or the new IAM code is
not necessary for the failure; the forward/reverse fixture counterfactual identifies it.

- **Initiating code change:** `aee7ffc859951a459d78cc0f431f31723208699b` (2023-10-27)
  moved `Names.application_configuration_secret` to the appconfig naming scheme but left
  this fixture seeding `C4Datastore<Env>ApplicationConfiguration`.
- **Masking condition:** without the workflow's required `custom/config.json` and
  `custom/secrets.json`, full-suite collection fails before reaching these assertions.
  Supplying those files and locked dependencies exposes the actual failure; changing
  dependency versions or suppressing warnings is not the correction.
- **Visible failure:** the CLI looks for `C4AppConfigCgapUnitTest`, reports that it does not
  exist, and does not update the obsolete mocked key. Assertions see old ACCOUNT_NUMBER
  instead of `1234567890`, and `None` instead of the printed old account number.

The old PR-body claim was correct **only for the old merge base**, not current master.
Current master already fixes the fixture via `Names.application_configuration_secret`.
The added regression also pins the expected appconfig name and explicit CLI-name override;
all existing overwrite/encryption/access-key assertions remain exercised.

## IAM review and corrections

The IAM change itself did contain defects independently of that CI failure:

- The remediation session ceiling of 1800 failed local cfn-lint with **E3034** (IAM minimum
  is 3600). Both roles now enforce one hour; 1800 is caller guidance only, as explicitly
  accepted for this design.
- Trust rejects root, wildcard, malformed and STS-session principals, supports concrete
  cross-account/Identity Center roles, and checks the default 2048-character trust quota.
  JSON-array principals survive ConfigManager's stringification rather than only working
  through a mocked getter.
- S3 reads now require the owning account, with explicit cross-account denies that also
  cover bucket-policy grants to sessions. Known resource-authorized inspection actions
  use service ARNs; wildcard inventory checks owner context when AWS supplies it.
- Boundary mutation patterns no longer accidentally deny `DescribeVpcs`/`DescribeSubnets`.
  Tests check wildcard deny intersections, not just exact strings in inline policies.
- MFA remains required by default in trust. Unsupported downstream MFA checks were removed:
  AssumeRole credentials do not carry the MFA context needed for individual API checks.
  Logs `StopQuery` now uses its required wildcard resource rather than a log-group ARN.
- KMS documentation accounts for existing key-policy delegation to account IAM: enabling
  decrypt can take effect immediately. Default explicit decrypt denial is retained.
- README policy examples match complete generated statements, including resources and
  conditions. Local boundary references, non-exported role-name outputs, disabled-default
  parity, explicit actions, direct PassRole/AssumeRole denies and policy quotas are tested.

**Retained, explicitly accepted risk:** StartBuild and RetryBuild remain enabled without a
new restriction architecture. Buildspec/source/image/environment overrides execute under
existing service roles. Direct human denies/boundaries do not constrain those roles.
Workflow inputs, ECS service updates, credential-bearing diagnostic reads, source-identity
labels and KMS behavior are documented in the [operator guide](source/human_access_roles.rst).
No claim of a no-arbitrary-code sandbox or universally reversible remediation is made.

References: [IAM role session limits](https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-resource-iam-role.html),
[MFA API behavior](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_mfa_configure-api-require.html),
[CodeBuild overrides](https://docs.aws.amazon.com/codebuild/latest/APIReference/API_StartBuild.html),
[KMS default key policy](https://docs.aws.amazon.com/kms/latest/developerguide/key-policy-default.html).

## Supported offline validation

Local test runs used fake credentials, `/dev/null` credential/config files, metadata disabled,
and blocked outbound networking; real SDK requests were blocked for final synthesis/testing.
No role creation/assumption, CloudFormation operation, deployment, publishing or IAM application
was performed. In particular, `make alpha` was not used.

- **142 role tests**, **4 secrets tests**, **175 full-suite tests passed**.
- All five changed Python files pass flake8; operator reStructuredText parses cleanly.
- **21 IAM templates** pass cfn-lint without warnings: three app kinds, six feature modes
  (disabled, diagnosis, remediation, both, KMS, SSO), plus the three full default IAM stacks.
- **63 templates synthesized** with dummy configuration and mocked deployed-value lookups.
  All **45 existing-stack templates** are byte-identical to the controlled current-base
  synthesis, including IAM disabled-default output. All templates have zero cfn-lint errors.
- Conservative serialized inline sizes: diagnosis 9460 with KMS, remediation 6025, below
  the aggregate 10240-character limit; boundary below 6144. Trust also has a synthesis guard.

### Explicit limitations, not suppressed checks

Whole-repository flake8 reports **60 unchanged diagnostics** in unrelated files (current base
has 64; four fixture-formatting diagnostics were corrected). Broad cfn-lint reports the same
**63 legacy warnings** on branch and current base: unused parameters, hardcoded availability
zones, S3 ACL usage, deletion/update-replacement policy advice and an obsolete dependency.
No lint rules or CI checks were disabled to hide these.

Optional blue/green synthesis hit the same APP_DEPLOYMENT guard on branch and pristine
current base after two fixture approaches. This is a documented synthetic-validation limit,
not evidence warranting a repository/guard change. Foursight packaging was not attempted
because it requires deployed exports/infrastructure. Neither optional path is represented
as validated by the supported IAM matrix or by the unit suite.

## Deployment role (`*InfraDeployRole`) validation

Branch reconciled with current `master` (`646d333`, Chalice pruning and lock update) by merge.
Validation used a fresh Python 3.10 environment installed from that `poetry.lock` (boto3/botocore
1.43.108, awscli 1.46.1, foursight-core 5.10.3, cfn-lint 0.86.4), fake credentials, metadata
disabled, and sockets plus botocore HTTP sends blocked.

- **499 tests passed** (`tests src/tests`, also in reverse order); changed Python files pass flake8
  (including a pre-existing unused import removed from `datastore.py`); the operator
  reStructuredText parses without messages.
- **102 existing-stack templates** (CGAP/Fourfront/SMaHT x standalone/blue-green x S3 encryption
  off/default) are byte-identical before and after the change. Blue/green synthesized here by
  setting `app.deploy` before import.
- **12 IAM templates** (three apps x disabled, deploy, deploy with SSO settings, all three roles)
  pass cfn-lint with no findings. Datastore templates with the deploy role configured (three apps)
  give exactly the same legacy cfn-lint warnings as the unchanged datastore (10 W3045, 1 W3010)
  and no errors.
- Datastore key policy: with the deploy role configured, it adds two statements naming the role
  (via the IAM stack's `HumanDeployRoleArn` export) and leaves the existing ones unchanged.
  Every `AWS::KMS::Key` create/read/update action the role performs is allowed by both its IAM
  policy and the generated key policy, including the `PutKeyPolicy` that the CreateKey lockout
  check requires. Deletion, disabling, grants and direct encrypt/re-encrypt are not granted. A
  flag without principals leaves the key policy unchanged.
- Policy sizes, counted as IAM does (whitespace removed, account/region substituted): managed
  policies 5483/5322/5784/3929 characters (limit 6144); inline guardrail 5169 (limit 10240).
- With the deploy role enabled, the IAM templates differ from the previous head only in the deploy
  role and its new `InfraDeployTibannaPolicy`; disabled IAM templates are byte-identical.
- Image builds, pushes/retags and stack cleanup: the dcicutils `add-image-tag` and
  `unrelease-most-recent-image` code and a CloudFormation continue/rollback/delete/retain sequence
  were driven against locally answered botocore clients, and every API they call is allowed;
  AWS's documented `docker push` action set is allowed for this account's repositories; every
  CodeBuild project name the synthesized CodeBuild templates generate can be started and stopped.
  Explicit-deny precedence is tested for retries/batch builds, image deletion, other accounts and
  regions, non-`c4-*` stacks, service-role (`--role-arn`) requests, stack sets, termination
  protection and stack policies. From AWS's delete-handler permissions, the tests derive which
  resource types a stack deletion must retain (the data-bearing types and the S3 federator IAM
  user) and assert everything else is deletable. With all three roles enabled, the diagnose and
  remediate roles' resources are byte-identical to the previous head.
- ECS release commands: `deploy-ecs` (`--list`, `--kick`) and `identity-swap` (SMaHT, and
  Fourfront `--mirror`) were run end to end against locally answered ECS, Application Auto
  Scaling, CloudWatch and S3 clients. Every recorded call, evaluated with its actual parameters
  (cluster/service ARNs, scaling namespace and dimension, alarm names, env-bucket object keys),
  is allowed. The only S3 writes are the `main.ecosystem` objects. Negative cases cover other
  env-bucket objects, other accounts and regions, non-ECS scaling targets, object deletion and
  `RunTask`.
- Tibanna deployment (`tibanna_smaht deploy_tiger -e smaht-production` and `cleanup`): the
  IAM, Step Functions, Lambda, DynamoDB, S3 and KMS requests that tibanna (c8c49ea) and tibanna_ff
  (808baba) make, with names built as their source builds them (`tibanna_tiger_<env>_*` IAM
  resources, `<lambda>_tiger_<env>` functions, `tibanna_tiger_<env>[_costupdater]` state machines,
  `tibanna-master`), including the replace-on-conflict branches, are all allowed (525 deploy
  requests; 492 of them are refused without the new policy). Negative cases cover policies and
  groups outside the namespace, other accounts and regions, attaching other policies (including
  `AdministratorAccess`) to Tibanna's roles or group, passing each role to the wrong service or
  resource, policy versions, adding group users, and deny precedence of the human-access
  protections inside the namespace. Workflow starts, sync starts and redrives, function
  invocation, worker launches with Tibanna's instance profile, job-table deletion and item writes
  stay denied. The Tibanna code was read, not run (it is not a dependency of this repository).
- Identity Center bundle for `SMaHT-Deployment-Manager` (account 517723527581, us-east-1):
  - It is regenerated by `python -m src.commands.render_deploy_policy_bundle`, and its `--check`
    passes.
  - Its five documents equal the opt-in role's CloudFormation-rendered documents with the
    account and Region substituted.
  - It contains no intrinsics or placeholders, only that account and Region, and only standard
    IAM policy elements.
  - It fits the quotas: managed 5483/5322/5784/3929 of 6144 characters; inline 5169 of 10240
    non-whitespace characters and under 32768 bytes.
  - Holders are denied changes to the bundle's own policies.
  - The README deployment example is the same policy, concrete for that account and Region.
- Pre-existing defect fixed: `deploy-ecs` imported `CGAP_ECS_REGION`, which the locked
  dcicutils 8.19.0 does not define, so the command failed at import (reproduced with the
  regression test against the previous source: `ImportError`). It now uses `ECSUtils.REGION`
  (`us-east-1`, as before). Flags, output and exit codes are unchanged.
- Coverage is checked against official AWS data in `tests/data/aws_iam_deploy_reference.json`:
  CloudFormation resource-provider handler permissions for all 47 resource types in the
  synthesized templates and the Foursight SAM output, and the AWS Policy Generator action and
  condition-key catalogue (now including the EC2 condition keys, for `ec2:InstanceProfile`).
  Every handler permission is granted or excluded with a reason; 14 handler-declared names are not
  IAM actions at all and are recorded as such.
- The AWS CLI's own change-set and S3-upload code was driven against stubbed clients with
  role-shaped (`ASIA…` + session token) credentials; `--upload-change-set` was confirmed to use only
  the Docker-mounted `custom/aws_creds` directory.

Not validated: any live AWS call, role assumption or deployment; Foursight `chalice package`
(needs deployed exports and package downloads; its resource types are listed from Chalice/SAM);
behaviour of CloudFormation when a role session expires during a long stack operation.
