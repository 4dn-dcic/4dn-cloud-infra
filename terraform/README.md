# Terraform migration

Additive native Terraform modules and offline adoption tooling, aligned with the current
Troposphere contracts in `src/parts/`. **CloudFormation/Chalice remain operational owners.**
Nothing in this PR authorizes deployment or claims a no-op plan against an account.
See [PARITY.md](PARITY.md) for the contract comparison, intentional differences and adoption gates.

## Modules and ownership

| Scope | Modules |
|---|---|
| Ecosystem/account, once in `shared/` | `network`, `network-data`, `srce-network`, `iam`, `ecr`, `logging`, `shared-secrets`, `codebuild-credentials` |
| Environment, in `envs/<env>/` | `appconfig`, `datastore`, `redis`, `codebuild`, `ec2-service`, standalone `ecs-app` |
| Ecosystem, **once for both colors** | `ecs-app` with `deployment_paradigm = "blue_green"` |
| Fresh state infrastructure | `bootstrap` |

`datastore.variant` consolidates **standard**, **srce** and **slim** contracts. Slim owns only
RDS/secret/parameter/subnet group and legacy `es-` Elasticsearch 6.8 domains; no buckets, queues
or KMS key. SRCE consumes the **Database** network. Redis consumes that same DB network;
ECS, CodeBuild, Foursight and SRCE Sentieon consume **Application**, never Compute.

`srce-network` owns the seven SGs and cross-VPC rules of the Application, Database and retained
`srce-network-compute` shells. It does **not** own IT VPCs, subnets, routes, NAT, endpoints,
FlowLogs or CloudTrail. Central IT retains account logging/CloudTrail ownership.
`network-data` remains read-only for Fourfront's unmanaged legacy VPC.

The three account directories remain in `accounts/`; the two Fourfront environments share one
account. See [OWNERSHIP.md](OWNERSHIP.md). Newly implemented modules are not enabled in those
roots without discovery. [examples/srce/main.tf](examples/srce/main.tf) demonstrates typed
producer/consumer wiring for an **environment root**, with reviewed sibling shared outputs as
input. It is not a fourth account or a deployment prescription.

## Offline validation

Install the locked Python dependencies (`make build`) and Terraform **1.15.8** for mock-provider
tests. `tibanna` and `tibanna-ff` share a Python namespace: for the generic/SRCE matrix select the
locked primary package after installation, as in `.github/workflows/terraform.yml`.

```bash
terraform/tools/validate.sh schema  # fmt check, init -backend=false -input=false, validate
terraform/tools/validate.sh lint    # tflint; any failing child makes the parent fail
mkdir -p .parity                   # pytest creates/clears only the pytest child directory
TF_PARITY=1 PYTHONPATH=tests/offline:. poetry run pytest -q --basetemp=.parity/pytest
```

The opt-in Python sandbox replaces operator config reads with synthetic JSON, removes ambient
config/credential fallbacks, and blocks socket and botocore API calls **before app imports**.
Native parity uses `terraform test` with **mock providers and plan-only run blocks** in scratch
copies. Only computed IDs/ARNs are mocked; containers, policies, listeners, dependencies and
configuration come from the actual modules. No real-provider plan/apply/import runs.

`CAPTURE_CFN_DIR=.parity/synth` additionally saves deduplicated synthetic CFN templates for
`cfn-lint`. Checkov is advisory; run offline with `--skip-download` and report its nonzero exit
and findings rather than suppressing them. CI's advisory lint jobs preserve child exit statuses.

```bash
checkov -d terraform/modules --framework terraform --compact --skip-download
```

## Adoption gates (for a separately authorized operation)

1. Inventory every physical resource, exact name, current owner and external consumer; update
   the ownership ledger. Keep IT networking and account singletons out of environment states.
2. **IAM requires `iam.ecosystem_resources` / `ecosystem_resources`:** the complete inventory for
   every environment sharing the role/user, not just `env_name`. Preserve discovered role/user,
   instance-profile and managed-policy names. See `docs/source/iam_inventory.rst` and PARITY.md.
3. Harden state before any credential-bearing resource is adopted. Terraform owns secret
   containers, not ongoing content. **Adopt each `aws_secretsmanager_secret_version` too**:
   `ignore_changes` protects updates, **not creates**. Otherwise first apply would overwrite a
   live GAC, DockerHub credential or DB password. Never reset populated JSON to these templates.
4. Generate suggestions from a **saved metadata-only** CFN inventory:
   ```bash
   python terraform/tools/import_from_cfn.py --module datastore \
     --module-address module.datastore --stack-file <saved-inventory.json>
   ```
   Consolidated variants require an exact `--address-map` (logical ID -> relative Terraform
   address). Unmapped/duplicate resources fail closed; partial output is not a complete import
   plan. Inline policies, managed attachments, bucket satellite resources and default egress
   require separate adoption; see PARITY.md. The tool never executes a command.
5. Reconcile generated names/tags, adopt log groups instead of deleting them, and review the
   **entire** resulting no-op plan, including secrets, IAM attachments and provider defaults.
   Any RDS/OpenSearch replacement is a stop signal. Default PostgreSQL is **17.6**; explicitly
   configured older versions drive **both engine and parameter family**. Carry pins into root
   inputs before reviewing a migration; do not infer upgrade authorization from the default.
6. Standard -> SRCE datastore ownership is **not** a data migration. Require a retained-data,
   backup/restore and rollback plan; identical physical bucket/DB/domain names cannot be owned
   by two stacks/states. Freeze CFN writes during adoption and retain data before any later
   CFN retirement. `prevent_destroy` blocks destruction rather than orphaning like CFN Retain.
7. CFN exports must outlive both `list-imports` consumers and runtime `ConfigManager.find_stack*`
   consumers. Terraform outputs are not CFN exports. Foursight's Chalice packaging/check code
   remains in Python; its SRCE package group is SMaHT and its explicit Foursight GAC must be
   populated before packaging. A new identity does not select a VPC or retire the old stack.

Deployment-only evidence still required: real subnet membership/AZs/routing, IAM/key policies,
certificate hostname/DNS, log delivery, build source/image provenance, DB restore/upgrade safety,
and Falcon prepare-and-exit-zero/loader/headroom behavior. CrowdStrike remains off by default.
