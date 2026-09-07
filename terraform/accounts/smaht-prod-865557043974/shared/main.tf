# ============================================================================================
# smaht-prod (865557043974) — SHARED root (ecosystem-scoped modules; plan §1.1, §2.4).
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["865557043974"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "smaht-prod-865557043974"
    scope      = "shared"
    ecosystem  = "main"
  }
}

module "network" {
  source            = "../../../modules/network"
  subnet_pair_count = 2 # smaht-prod config does not set subnet.pair_count -> default 2
  region            = "us-east-1"
  name_prefix       = "c4-network-main"
  tags              = local.common_tags
}

# Required operator inventory, not a guessed subset from production.
variable "iam_ecosystem_resources" {
  type = object({ buckets = set(string), queues = set(string), search_domains = set(string), repositories = set(string), runtime_secrets = set(string), kms_keys = set(string) })
}

module "iam" {
  source              = "../../../modules/iam"
  env_name            = "production"
  app_kind            = "smaht"
  ecosystem_resources = var.iam_ecosystem_resources
  tags                = local.common_tags
}

module "logging" {
  source              = "../../../modules/logging"
  env_name            = "production"
  app_kind            = "smaht"
  deployment_paradigm = "standalone"
  tags                = local.common_tags
}

module "ecr" {
  source                    = "../../../modules/ecr"
  env_name                  = "production"
  app_kind                  = "smaht"
  iam_ecs_assumed_role_name = module.iam.ecs_assumed_role_name
  tags                      = local.common_tags
}

module "shared_secrets" {
  source = "../../../modules/shared-secrets"
  tags   = local.common_tags
}
