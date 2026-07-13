# ============================================================================================
# fourfront-prod (643366669028) — SHARED root. THE 4dn ACCOUNT (plan §1.2, §3 Phase 1b).
#
# This account hosts the fourfront-production blue/green pair on a LEGACY, UNMANAGED VPC
# (vpc-066421dc99161d0ea, 172.31.0.0/16 — a network this repo never created). Terraform therefore
# gets a network-DATA wrapper here, NEVER a network import: it holds only data sources and can
# never modify or destroy the IT-managed network. There is deliberately NO modules/network here.
#
# iam / logging / ecr / shared-secrets are PENDING PHASE-0 DISCOVERY (plan §2.4): the physical ff
# stack names must be enumerated from AWS (aws cloudformation list-stacks) before their modules can
# be wired and imported. They are intentionally left as TODOs rather than fabricated. See
# accounts/fourfront-prod-643366669028/DISCOVERY.md.
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["643366669028"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "fourfront-prod-643366669028"
    scope      = "shared"
  }
}

# Legacy unmanaged VPC exposed as data sources (values from custom_directories/4dn-*/template.config.json).
module "network_data" {
  source                = "../../../modules/network-data"
  fourfront_vpc_id      = "vpc-066421dc99161d0ea"
  fourfront_subnet_ids  = ["subnet-0289fd123573a5d6f", "subnet-002fd63c6e10a102b"]
  fourfront_rds_sg_id   = "sg-00a1706c6a3fa86af"
  fourfront_https_sg_id = "sg-0d550dd8ac0529d3b"
}

# --- PENDING PHASE-0 DISCOVERY (do not enable until the ff stack names are enumerated) ---
# module "iam"            { source = "../../../modules/iam"            env_name = "fourfront-production-green" app_kind = "ff" ... }
# module "logging"        { source = "../../../modules/logging"        env_name = "fourfront-production-green" app_kind = "ff" ... }
# module "ecr"            { source = "../../../modules/ecr"            env_name = "fourfront-production-green" app_kind = "ff" ... }
# module "shared_secrets" { source = "../../../modules/shared-secrets" ... }
