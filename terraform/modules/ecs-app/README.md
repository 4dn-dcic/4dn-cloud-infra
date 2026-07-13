# `ecs-app` — DEFERRED in this PR

Consolidated compute module from `src/parts/ecs.py` + `ecs_blue_green.py` + `fourfront_ecs.py`
(plan §5.1). Not yet implemented — see `terraform/OWNERSHIP.md` and `terraform/README.md`
("Deferred modules") for the rationale (largest module; depth-over-breadth). Env roots reference it
only as commented `# module "ecs_app"` TODOs, so nothing here breaks `terraform validate`.

## When implemented, it must faithfully carry (from the three source parts)

- `ECS::Cluster` (Fargate + Spot), **5 task definitions** (portal, indexer, ingester,
  initial-deployment, deployment), **3 services** (portal, indexer, ingester — the two deployment
  task defs have no service; ecs.py:131-143), 2 security groups, ALB (target group / listener /
  load balancer), 4 CloudWatch alarms.
- One module, parameterized by the exact knobs that differ across the three parts (plan §5.1 table):
  `app_kind` (cgap/ff/smaht), `deployment_paradigm` (standalone/blue_green), `include_ingester`
  (bool), `identities` (single or blue/green), `portal_cpu`/`portal_memory`, `extra_container_env`.
- **Scope caveat (critical):** `deployment_paradigm = "blue_green"` is ecosystem-scoped
  (`ecs_blue_green.py:38`) → the instantiation belongs in the account `shared/` root; `standalone`
  is env-scoped → the `envs/<env>/` root. Determine the live variant per env from Phase-0 discovery.
- ECS Service → ALB Listener ordering: explicit `depends_on` (the 3 `DependsOn` sites, plan §6.7).
- Consumes network/iam/ecr/logging via `data.terraform_remote_state`.
- Output `application_url` (repoints §2.3 consumer #7 after Phase 5).
