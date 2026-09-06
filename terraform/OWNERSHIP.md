# Terraform migration ownership ledger

Key: **(module, account, scope-instance)**. All listed code is authored, but **no adoption or
account plan has been performed** by this PR. CloudFormation/Chalice remain operational owners;
IT retains its networks. Never record Terraform ownership until an authorized, fully reviewed
no-op adoption establishes it. Physical stack/resource names still require discovery.

## Shared roots (one per account)

| Module | Account | Scope | Owner | Status |
|---|---|---|---|---|
| network | 537626822796 | shared | CFN | authored; account root wired, adoption pending |
| iam | 537626822796 | shared | CFN | authored; complete ecosystem inventory required |
| logging | 537626822796 | shared | CFN | authored; retained logs, adoption pending |
| ecr | 537626822796 | shared | CFN | authored; adoption pending |
| shared-secrets | 537626822796 | shared | CFN | authored; container AND version adoption pending |
| network | 865557043974 | shared | CFN | authored; account root wired, adoption pending |
| iam | 865557043974 | shared | CFN | authored; complete ecosystem inventory required |
| logging | 865557043974 | shared | CFN | authored; retained logs, adoption pending |
| ecr | 865557043974 | shared | CFN | authored; adoption pending |
| shared-secrets | 865557043974 | shared | CFN | authored; container AND version adoption pending |
| network-data | 643366669028 | shared | IT/unmanaged legacy | read-only wrapper; never imports VPC |
| iam | 643366669028 | shared | CFN | authored; discovery/wiring pending |
| logging | 643366669028 | shared | CFN | authored; discovery/wiring pending |
| ecr | 643366669028 | shared | CFN | authored; discovery/wiring pending |
| shared-secrets | 643366669028 | shared | CFN | authored; discovery/wiring pending |
| srce-network | SRCE account (not assumed) | shared | IT VPCs; CFN SGs/rules | authored; owns only seven SGs/rules across App/DB/Compute |

`codebuild-credentials` is authored but **must be inventoried once per account**, including any
SourceCredential currently declared by an env CFN stack. No account root assumes a new token
or a second credential owner. `bootstrap` is new state infrastructure, not a migrated part.

## Environment roots

| Module | Account | Scope instance | Owner | Status |
|---|---|---|---|---|
| appconfig | 537626822796 | smaht-wolf | CFN | authored; container AND version adoption pending |
| datastore | 537626822796 | smaht-wolf | CFN | authored; adoption pending; CFN runtime-discovery consumers remain |
| redis | 537626822796 | smaht-wolf | CFN | authored; adoption pending |
| ecs-app | 537626822796 | smaht-wolf | CFN | authored; discovery/wiring pending |
| codebuild | 537626822796 | smaht-wolf | CFN | authored; discovery/wiring pending |
| appconfig | 865557043974 | production | CFN | authored; adoption pending |
| datastore | 865557043974 | production | CFN | authored; adoption pending; CFN runtime-discovery consumers remain |
| redis | 865557043974 | production | CFN | authored; adoption pending |
| ecs-app | 865557043974 | production | CFN | authored; discovery/wiring pending |
| codebuild | 865557043974 | production | CFN | authored; discovery/wiring pending |
| ec2-service (sentieon) | 865557043974 | production | CFN | authored; discovery/wiring pending |
| appconfig | 643366669028 | fourfront-production-blue | CFN | authored; discovery/adoption pending |
| appconfig | 643366669028 | fourfront-production-green | CFN | authored; discovery/adoption pending |
| datastore variant=slim | 643366669028 | fourfront-production-blue | CFN | authored; discovery/wiring pending |
| datastore variant=slim | 643366669028 | fourfront-production-green | CFN | authored; discovery/wiring pending |
| ecs-app | 643366669028 | determine live variant | CFN | authored; standalone belongs per-env; blue_green belongs ONCE in shared |

Higlass/JupyterHub and SRCE datastore/Redis/ECS/Sentieon are authored as variants of the native
modules, not separate duplicate states. Their account/scope rows must be established by discovery
before enabling. The two-color ECS scope must never be represented in both environment roots.

## Coexistence gates

- Follow [PARITY.md](PARITY.md) for native satellites, name overrides, shared IAM attachment
  adoption and explicit representation differences. Schema validation is not a no-op plan.
- Freeze CFN writes to each adopted scope; preserve/import existing log groups and data resources.
- Do not retire a CFN stack until export imports **and runtime `ConfigManager.find_stack*`
  consumers** are gone. Datastore, network, ECS and Sentieon have such consumers.
- Foursight/Chalice packaging and check code remain Python-owned. New SRCE identity/network
  metadata does not automatically retire any existing Foursight stack.
- Central IT owns CloudTrail and supplied VPC infrastructure. `srce-network-compute` is retained.
