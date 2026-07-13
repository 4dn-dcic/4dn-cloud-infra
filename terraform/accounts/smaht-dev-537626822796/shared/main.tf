# ============================================================================================
# smaht-dev (537626822796) — SHARED root (ecosystem-scoped modules; plan §1.1, §2.4).
# Instantiates EXACTLY the ecosystem-shared parts, once per account: network, iam, logging, ecr,
# shared-secrets. Env-scoped parts (datastore, appconfig, redis, ecs-app, ...) live under envs/.
# The SHARING invariant is structural here: an ecosystem resource can only be declared in this one
# root, so it can never end up in two Terraform states.
# ============================================================================================

provider "aws" {
  region = "us-east-1"

  # Hard failure if credentials point at the wrong account (plan §2.4 directory-per-scope rationale).
  allowed_account_ids = ["537626822796"]

  default_tags {
    tags = local.common_tags
  }
}

locals {
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "smaht-dev-537626822796"
    scope      = "shared"
    ecosystem  = "smaht-development"
  }
}

module "network" {
  source            = "../../../modules/network"
  subnet_pair_count = 6 # smaht-wolf config: subnet.pair_count = 6
  region            = "us-east-1"
  name_prefix       = "c4-network-main"
  tags              = local.common_tags
}

module "iam" {
  source            = "../../../modules/iam"
  env_name          = "smaht-wolf"
  app_kind          = "smaht"
  s3_encrypt_key_id = "27d040a3-ead1-4f5a-94ce-0fa6e7f84a95" # smaht-wolf config: s3.encrypt_key_id
  tags              = local.common_tags
}

module "logging" {
  source              = "../../../modules/logging"
  env_name            = "smaht-wolf"
  app_kind            = "smaht"
  deployment_paradigm = "standalone"
  tags                = local.common_tags
}

module "ecr" {
  source                    = "../../../modules/ecr"
  env_name                  = "smaht-wolf"
  app_kind                  = "smaht"
  iam_ecs_assumed_role_name = module.iam.ecs_assumed_role_name
  tags                      = local.common_tags
}

module "shared_secrets" {
  source = "../../../modules/shared-secrets"
  tags   = local.common_tags
}
