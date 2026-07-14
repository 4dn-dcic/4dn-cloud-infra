# Terraform migration (`terraform/`)

Terraform codebase and migration tooling for the Troposphere → Terraform migration of
4dn-cloud-infra. **Specification:** the revised plan (`tf-plan-rev-p8/report.md`). This tree
delivers the Terraform CODE only — it performs **no** AWS access (no `plan`/`apply`/`import`
against real accounts). Everything here validates offline.

> Stacked on PR #97 (SRCE). This tree is built from PR #97's head, so its ground truth is the
> `src/parts/*.py` on that branch (which includes `srce_*.py` and `shared_secrets.py`), not the
> plan's `master@d9c9e65` snapshot.

## The load-bearing idea: SHARING scope → directory scope

Every C4Part carries a `SHARING` scope (`src/mixins.py`). A module's Terraform **root must match
its scope**, so no physical resource is ever owned by two Terraform states (plan §1.1):

- **ecosystem-shared** (network, network-data, iam, ecr, logging, shared-secrets) → the account's
  `shared/` root, instantiated **once per account**.
- **env-scoped** (appconfig, datastore, datastore-slim, redis, ecs-app, codebuild, ec2-service) →
  each `envs/<env>/` root, instantiated **once per environment**.

Directory-per-scope (not workspaces) makes this structural: an ecosystem resource can only be
declared in one root, and each root has its own `backend.tf` + provider (a wrong-account mistake is
a hard failure, not a silent cross-account apply). See plan §2.4.

## Layout

```
terraform/
├── modules/            # scope-agnostic, one per C4Part (see "Modules" below)
├── accounts/
│   ├── smaht-dev-537626822796/{shared, envs/smaht-wolf}
│   ├── smaht-prod-865557043974/{shared, envs/production}
│   └── fourfront-prod-643366669028/{shared, envs/{fourfront-production-blue,green}}
├── tools/import_from_cfn.py   # offline import-command generator (+ fixtures/)
├── versions.tf                # canonical provider pins (copied per root)
├── OWNERSHIP.md               # (module, account, scope-instance) ledger
└── README.md
```

**Three accounts, not four environments** (plan §1.2): `4dn-dev`/`4dn-prod` are the SAME account
(643366669028) — the blue/green fourfront-production pair on a **legacy, unmanaged VPC**. That
account gets `network-data` (data sources over `vpc-066421dc99161d0ea`), never a `network` import.

## Modules

Implemented (faithful ports, validated offline): `bootstrap`, `network`, `network-data`, `iam`,
`ecr`, `logging`, `shared-secrets`, `appconfig`, `datastore`, `redis`, `srce-network`.

**Deferred** in this PR (documented, no `.tf` — see OWNERSHIP.md for why and what they need):
`ecs-app`, `datastore-slim`, `codebuild`, `ec2-service`, and the SRCE compute/datastore/redis/
sentieon parts. Deferred modules appear ONLY as commented `# module "…"` TODOs in the roots — never
as live blocks — so `terraform validate` stays green. This follows the plan's explicit
depth-over-breadth guidance: complete the foundational layer + a full env exemplar (datastore) well,
rather than all modules shallowly.

### SRCE (PR #97)

#97 is open/unmerged; this tree is built on its head. Its SRCE networks export IT-provided VPC/
subnet IDs — conceptually identical to `network-data` (plan §1.3). We therefore deliver
`modules/srce-network` **born in Terraform** as a data-source wrapper over the IT-provided SRCE
VPCs (Application/Database/Compute), and **explicitly defer** the SRCE-created cross-VPC security
groups and the `srce_datastore`/`srce_ecs`/`srce_redis`/`srce_sentieon` parts to a follow-on. This
is the plan-blessed "either TF modules following the externally-provided-IDs pattern, or a
documented deferral" — we did the former for the network IDs, the latter for the rest.

## Safety gates (non-negotiable — preserved in code + here)

- **Log groups**: `lifecycle { prevent_destroy = true }` in BOTH `modules/logging` and the flow-log
  group in `modules/network` (faithful to `DeletionPolicy=Retain`; plan §6.2). `prevent_destroy`
  errors out of any destroying plan — a workflow change vs CFN's "orphan and keep alive"; flagged
  to ops.
- **Secret content — container vs. version (HIGH)**: `lifecycle { ignore_changes = [secret_string] }`
  in `modules/appconfig`, `modules/shared-secrets`, and the RDS master secret in `modules/datastore`
  — Terraform owns each secret's *existence*, never its live content (plan §5.3). **This only
  protects updates, not creates.** `aws_secretsmanager_secret_version` is a separate Terraform
  resource with no CFN LogicalResourceId of its own, so `import_from_cfn.py` cannot discover it from
  a stack-resources JSON — it instead always emits an `# ACTION-REQUIRED` block after every secret
  container import telling you to adopt the `*_version` resource too (metadata-only version-id
  lookup + the import command). **Skipping that adoption means the first `terraform apply` after
  import creates a fresh version and overwrites the live secret** (the GAC content, the DockerHub
  PAT, or the RDS master password). Verify with `terraform plan -detailed-exitcode` per step 3 below
  — for `datastore`, `+ random_password.rds` (a local-only value with no AWS resource, inert once the
  secret version is adopted and ignored) is the *only* permitted line; any secret/RDS diff beyond
  that is a stop-and-fix signal, not something to apply through.
- **RDS**: `deletion_protection = true`, `storage_encrypted = true` (faithful to datastore.py).
  Any plan that would **replace** the RDS instance or an OpenSearch domain is an auto-abort — the
  migration's true point of no return (plan §7.4).
- **State bucket hardening** (`modules/bootstrap`): SSE-KMS, versioning, full public-access block,
  TLS-only bucket policy, `prevent_destroy`. This must exist BEFORE the appconfig apply (initial
  `secret_string`) and the codebuild PAT ever put secret material in state (plan §8.3).

`checkov` flags the faithful wildcard-IAM policies (`Resource:['*']`) and some bucket/log/secret KMS
defaults. Those findings are **expected** for a like-for-like port (plan §8.1, §10.4) — the CI
checkov job is non-blocking; do NOT alter faithful resources to satisfy it. Tightening is a
separate, reviewed follow-on.

## Local validation (offline)

```bash
terraform fmt -check -recursive terraform/
# per root:
cd terraform/accounts/<account>/<shared-or-env-root>
terraform init -backend=false && terraform validate
tflint            # advisory
checkov -d . --framework terraform --compact   # expect faithful-port findings
```
Structural invariants are also enforced by `src/tests/test_terraform_structure.py` (runs under
`make test`) and the `.github/workflows/terraform.yml` CI job (separate from, and non-blocking to,
the Python CI).

## Migration runbook pointers (from the plan — this PR does NOT execute any of it)

1. **Phase 0 — bootstrap per account**: apply `modules/bootstrap` with LOCAL state, then point each
   root's `backend.tf` at the bucket/table it creates. Run **discovery** (`aws cloudformation
   list-stacks` + `describe-stack-resources`) and record it in `accounts/<account>/DISCOVERY.md`.
   Physical stack/resource names come from discovery, **never** derived from config (plan §1.1).
2. **Import (scripted, imperative)**: `terraform/tools/import_from_cfn.py` reads a saved
   `describe-stack-resources` JSON and emits `terraform import` commands mapping CFN logical IDs to
   the Terraform addresses used in these modules. Covers every implemented module that requires an
   import — `network`, `iam`, `logging`, `ecr`, `shared-secrets`, `appconfig`, `datastore`, `redis`
   (`--list` prints the full set); `bootstrap` is fresh local state and `network-data`/
   `srce-network` are data-source-only wrappers, so none of the three are ever imported. Runs
   **offline**:
   ```bash
   python3 terraform/tools/import_from_cfn.py --module network \
       --module-address module.network --stack-file terraform/tools/fixtures/network.json
   ```
   Any module whose CFN resources include a `AWS::SecretsManager::Secret` (`datastore`,
   `shared-secrets`, `appconfig`) prints an `# ACTION-REQUIRED` secret-version adoption block after
   each container import — see the safety-gate bullet above; do not apply before following it.

   **Importing IAM inline policies**: `iam.py`'s inline role/user `Policies=[...]` are embedded in
   the CFN Role/User resource, not separate LogicalResourceIds, so the tool has nothing to read them
   from. Their Terraform import ID is always `<role-or-user-name>:<policy-name>` (no AWS lookup
   needed — the role/user name comes from the import above, the policy name is a literal in
   `modules/iam/main.tf`):
   ```
   terraform import 'module.iam.aws_iam_role_policy.ecs_secret_manager' '<ecs-role-name>:ECSSecretManagerPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_management'     '<ecs-role-name>:ECSManagementPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_es'             '<ecs-role-name>:ECSESAccessPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_sqs'            '<ecs-role-name>:ECSSQSAccessPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_logging'        '<ecs-role-name>:ECSLoggingPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_ecr'            '<ecs-role-name>:ECSECRPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_cfn'            '<ecs-role-name>:ECSCfnPolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_s3'             '<ecs-role-name>:ECSS3Policy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_web_service'    '<ecs-role-name>:ECSWebServicePolicy'
   terraform import 'module.iam.aws_iam_role_policy.ecs_kms'            '<ecs-role-name>:ECSKMSPolicy'
   terraform import 'module.iam.aws_iam_role_policy.autoscaling'        '<autoscaling-role-name>:ECSPortalAutoscalingPolicy'
   terraform import 'module.iam.aws_iam_role_policy.flowlog'            '<flowlog-role-name>:ECSCWLoggingAccess'
   terraform import 'module.iam.aws_iam_role_policy.dev_management'    '<dev-role-name>:ECSManagementPolicy'
   terraform import 'module.iam.aws_iam_role_policy.dev_es'            '<dev-role-name>:ECSESAccessPolicy'
   terraform import 'module.iam.aws_iam_role_policy.dev_s3'            '<dev-role-name>:ECSS3Policy'
   terraform import 'module.iam.aws_iam_role_policy.dev_kms'           '<dev-role-name>:ECSKMSPolicy'
   terraform import 'module.iam.aws_iam_role_policy_attachment.dev_managed["cloudwatch_ro"]' '<dev-role-name>/arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess'
   # ...repeat dev_managed for the other 9 AWS-managed policy ARNs in modules/iam/main.tf
   terraform import 'module.iam.aws_iam_user_policy.s3_federator_s3'  '<s3-federator-user-name>:ECSS3Policy'
   terraform import 'module.iam.aws_iam_user_policy.s3_federator_sts' '<s3-federator-user-name>:ECSSTSPolicyforS3Access'
   terraform import 'module.iam.aws_iam_user_policy.s3_federator_kms' '<s3-federator-user-name>:ECSKMSPolicy'
   ```
3. **No-op-plan verification** (plan §4.4) — after every import, before proceeding:
   ```bash
   terraform validate
   terraform apply -refresh-only      # review the refresh diff by hand
   terraform plan -detailed-exitcode  # 0 = no changes (required); 2 = incomplete import, fix HCL
   ```
   Read every line — a compensating add+destroy can net to "0 changes". For datastore, a second
   engineer reads the full plan.
4. **Retain-then-bake-then-delete** (plan §4.3): import while the CFN stack still exists; verify a
   no-op plan; bake (≥1 wk leaf, ≥2 wk datastore) with CFN writes frozen; set `DeletionPolicy:
   Retain` on any resource lacking it and redeploy; only then delete the CFN stack. Deleting a CFN
   stack without Retain destroys the live resource out from under Terraform — the single most
   important step.
5. **Phase-7 consumer checklist** (plan §2.3) — a CFN stack may be deleted only when `aws
   cloudformation list-imports` is empty for all its exports (necessary, not sufficient) AND every
   runtime boto3 consumer of its outputs is repointed/retired AND the ledger sign-off + retain step
   are done. Re-run `grep -rn "find_stack_output\|find_stack_outputs\|find_stack_resource\|find_stack("
   src/` before each deletion. The load-bearing consumers, by stack:
   - **datastore** (long pole — 5 consumers): `application_configuration_secrets.get_es_url`;
     `stack.py` `ES_HOST` (the `+ ":443"` TypeError crash path if it returns None);
     `setup_tibanna.py`; `assure_global_env_bucket.py`; `appconfig.py get_env_bucket`; plus generic
     tooling (`find_resources.py`, `auto/utils/aws.py`). The datastore CFN stack must OUTLIVE all of
     these — Terraform datastore outputs are published name-compatibly for the repoint.
   - **network**: the three Foursight constructors' `get_security_ids`/`get_subnet_ids`.
   - **ecs**: `ecs.get_application_url`.
   - **sentieon**: `get_server_ip`.

## Coexistence freeze

Once `terraform import` begins on a scope instance, STOP running
`cli provision <part> --upload-change-set` against it (a CFN changeset after import silently
invalidates Terraform's cached state). Plus, from Phase 1 onward, **no new Troposphere Parts** — new
infra lands as Terraform modules. See `docs/source/making_stack_changes.rst` and OWNERSHIP.md.
