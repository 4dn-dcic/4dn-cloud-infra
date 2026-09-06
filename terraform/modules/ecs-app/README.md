# ecs-app

Native consolidated standalone/Fourfront/blue-green and SRCE ECS/ALB module.
Standalone belongs in the environment root; **blue_green belongs once in shared**, not per color.
See `variables.tf`, `tests/test_terraform_parity.py` and `terraform/PARITY.md` for the full contract.

TLS forwarding-listener dependencies, task sizing/logging, optional off-by-default Falcon
prepare-and-exit-zero wiring and variant service/alarm counts are compared with current CFN.
Supply discovered physical name overrides for adoption; defaults are not discovery.
