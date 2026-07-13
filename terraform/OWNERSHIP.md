# Terraform migration ownership ledger

Keyed by **(module, account, scope-instance)** per plan §7.1 — the keying that makes double-ownership
structurally impossible to record (a shared resource has exactly one row per account). Every engineer
touching either CloudFormation or Terraform **checks this table first** and updates it the moment a
module's no-op plan is confirmed (Terraform becomes operational owner). CFN-stack deletion is a
separate, later event recorded in the Status column.

Legend — **Owner**: which system is the operational owner today (CFN until a verified no-op plan
flips it). **Status**: `pending` = Terraform authored, not yet imported/applied; `not-implemented`
= module deferred in this PR (no `.tf` yet); `frozen` = CFN-owned and write-frozen. **Scope
instance**: `shared` (ecosystem, one per account) or the environment name (env-scoped).

> This PR delivers the Terraform CODE only. It performs **no** imports, plans, or applies against
> AWS (hard safety limit). Every row is therefore `pending` or `not-implemented`; none is TF-owned.

## Ecosystem-shared modules (scope instance = `shared`, one per account)

| Module | Account | Scope | Owner | CFN stack (from discovery) | Status | Notes |
|---|---|---|---|---|---|---|
| network | 537626822796 (smaht-dev) | shared | CFN | `c4-network-…` (discover) | pending | implemented; import per Phase 1a |
| iam | 537626822796 | shared | CFN | `c4-iam-…` | pending | implemented |
| logging | 537626822796 | shared | CFN | `c4-logging-…` | pending | implemented; **prevent_destroy** on log groups |
| ecr | 537626822796 | shared | CFN | `c4-ecr-…` | pending | implemented |
| shared-secrets | 537626822796 | shared | CFN | `c4-shared-secrets-…` | pending | implemented (#97 part) |
| network | 865557043974 (smaht-prod) | shared | CFN | `c4-network-…` | pending | implemented |
| iam | 865557043974 | shared | CFN | `c4-iam-…` | pending | implemented |
| logging | 865557043974 | shared | CFN | `c4-logging-…` | pending | implemented |
| ecr | 865557043974 | shared | CFN | `c4-ecr-…` | pending | implemented |
| shared-secrets | 865557043974 | shared | CFN | `c4-shared-secrets-…` | pending | implemented |
| network-data | 643366669028 (fourfront) | shared (data-only) | **neither — unmanaged legacy VPC** | `c4-network-main-stack` retained until ff CFN consumers gone | frozen | implemented; **data sources only, never imported** (plan §3 Phase 1b) |
| iam | 643366669028 | shared | CFN | pending discovery | pending | module exists; wiring TODO until Phase-0 discovery |
| logging | 643366669028 | shared | CFN | pending discovery | pending | module exists; wiring TODO |
| ecr | 643366669028 | shared | CFN | pending discovery | pending | module exists; wiring TODO |
| shared-secrets | 643366669028 | shared | CFN | pending discovery | pending | module exists; wiring TODO |
| srce-network | (SRCE account, per #97) | shared (data-only) | IT/CFN | n/a (externally provided) | pending | data-source module delivered; SRCE SGs + srce datastore/ecs deferred |

## Env-scoped modules (scope instance = environment)

| Module | Account | Scope instance | Owner | CFN stack (from discovery) | Status | Notes |
|---|---|---|---|---|---|---|
| appconfig | 537626822796 | smaht-wolf | CFN | `c4-appconfig-smaht-wolf-…` | pending | implemented; **ignore_changes** on GAC content |
| datastore | 537626822796 | smaht-wolf | CFN | `c4-datastore-smaht-wolf-…` | pending | implemented; **blocks §2.3 consumers #1–#5**; RDS deletion_protection |
| redis | 537626822796 | smaht-wolf | CFN | `c4-redis-smaht-wolf-…` | pending | implemented |
| ecs-app | 537626822796 | smaht-wolf | CFN | `c4-ecs-smaht-wolf-…` | not-implemented | DEFERRED (ecs.py family) |
| codebuild | 537626822796 | smaht-wolf | CFN | `c4-codebuild-smaht-wolf-…` | not-implemented | DEFERRED (PAT-in-state; harden first) |
| appconfig | 865557043974 | production | CFN | `c4-appconfig-production-…` | pending | implemented |
| datastore | 865557043974 | production | CFN | `c4-datastore-production-…` | pending | implemented; blocks §2.3 consumers |
| redis | 865557043974 | production | CFN | `c4-redis-production-…` | pending | implemented |
| ecs-app | 865557043974 | production | CFN | `c4-ecs-production-…` | not-implemented | DEFERRED |
| codebuild | 865557043974 | production | CFN | `c4-codebuild-production-…` | not-implemented | DEFERRED |
| ec2-service (sentieon) | 865557043974 | production | CFN | `c4-sentieon-production-…` | not-implemented | DEFERRED (sentieon.ssh_key set in config) |
| appconfig | 643366669028 | fourfront-production-blue | CFN | pending discovery | pending | implemented |
| appconfig | 643366669028 | fourfront-production-green | CFN | pending discovery | pending | implemented |
| datastore-slim | 643366669028 | fourfront-production-blue | CFN | pending discovery | not-implemented | DEFERRED (legacy ES 6.8 variant) |
| datastore-slim | 643366669028 | fourfront-production-green | CFN | pending discovery | not-implemented | DEFERRED |
| ecs-app | 643366669028 | fourfront-production-blue/green | CFN | pending discovery | not-implemented | DEFERRED (fourfront_ecs.py) |

## Deferred modules (no `.tf` in this PR — see terraform/README.md "Deferred modules")

| Module | Source part(s) | Why deferred | What it needs |
|---|---|---|---|
| ecs-app | ecs.py + ecs_blue_green.py + fourfront_ecs.py | Largest, most-consolidated module (5 task defs, 3 services, ALB, alarms); blue/green scope caveat | Faithful consolidation per plan §5.1; live-variant discovery per env |
| datastore-slim | datastore_slim.py | Legacy ES 6.8 + parameter-injected VPC wiring; only the 4dn account, which has no fresh-account validation | Its own module + import session (plan §3 Phase 4) |
| codebuild | codebuild.py | GitHub PAT lands in state (`aws_codebuild_source_credential.token`) — state hardening must be re-verified first (plan §8.3) | Module + PAT-in-state review |
| ec2-service | ec2_common.py (higlass/jupyterhub/sentieon) | Optional, lowest-consequence per-env parts (plan §3 Phase 6) | Shared EC2 module + per-service instantiation |
