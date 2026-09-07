# Canonical provider/version constraints (plan §2.4). This file is COPIED verbatim into each
# account root (accounts/<account>/{shared,envs/<env>}). Each root also commits its own
# .terraform.lock.hcl (exact provider hashes) — mirror the Python side's lockfile discipline
# (pyproject.toml pins). The `random` provider is only required by roots that call the datastore
# module (RDS master-password generation); other roots require aws only.
terraform {
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.5"
    }
  }
}
