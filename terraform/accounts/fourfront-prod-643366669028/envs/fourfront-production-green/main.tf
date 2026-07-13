# ============================================================================================
# fourfront-prod (643366669028) / env fourfront-production-GREEN — ENV root.
# Green half of the blue/green pair; mirrors the blue root. Shares the account shared/ root
# (network-data) and the account-wide GLOBAL_ENV_BUCKET with blue (plan §1.2).
#
# Wired today: appconfig. DEFERRED: datastore-slim, ecs-app (see terraform/OWNERSHIP.md).
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["643366669028"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  env_name           = "fourfront-production-green"
  deploying_iam_user = "arn:aws:iam::643366669028:user/david.michaels" # 4dn-prod/template.config.json
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "fourfront-prod-643366669028"
    scope      = "env"
    env        = "fourfront-production-green"
    color      = "green"
  }
}

module "appconfig" {
  source              = "../../../../modules/appconfig"
  env_name            = local.env_name
  deployment_paradigm = "standalone"
  deploying_iam_user  = local.deploying_iam_user
  global_env_bucket   = "foursight-prod-envs"
  tags                = local.common_tags
}

# --- DEFERRED in this PR (see terraform/OWNERSHIP.md + terraform/README.md) ---
# module "datastore_slim" { source = "../../../../modules/datastore-slim" ... } # legacy ES 6.8 variant — NOT YET IMPLEMENTED
# module "ecs_app"        { source = "../../../../modules/ecs-app" ... }        # fourfront_ecs.py — NOT YET IMPLEMENTED
