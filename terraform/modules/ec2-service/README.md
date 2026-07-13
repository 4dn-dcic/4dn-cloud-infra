# `ec2-service` — DEFERRED in this PR

Shared EC2 module from `src/parts/ec2_common.py` (the base for `higlass.py` / `jupyterhub.py`, and
optionally `sentieon.py`'s EC2 instance). Not yet implemented; roots reference it only as commented
TODOs.

## When implemented, faithful to ec2_common.py / higlass.py / jupyterhub.py / sentieon.py

- `SecurityGroup` + rules, `EC2::Instance` with imperative `UserData` bootstrap (higlass/jupyterhub),
  optional ALB (target group / listener / load balancer). `aws_instance.user_data` is a 1:1 analog
  (plan §6.8) — do NOT imply full automation; these already require manual post-launch steps.
- Sentieon SG uses a hardcoded vendor CIDR `52.89.132.242/32` (sentieon.py) — port as a variable
  with that default (plan §8.4).
- Lowest-consequence, optional per-env parts (plan §3 Phase 6) — deferred last by design.
- Consumes network via `data.terraform_remote_state`.
