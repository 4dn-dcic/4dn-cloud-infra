# ============================================================================================
# fourfront-prod (643366669028) / env fourfront-production-BLUE — ENV root.
# The 4dn blue/green pair is realized as two STANDALONE env roots (blue + green), both sharing the
# account's shared/ root (network-data) — plan §1.2 point 3, §2.4, §5.1.
#
# Wired today: appconfig (env-scoped, works for ff). DEFERRED: datastore-slim (the legacy ES 6.8 /
# parameter-injected variant) and ecs-app — see terraform/OWNERSHIP.md + terraform/README.md.
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["643366669028"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  env_name = "fourfront-production-blue"
  # 4dn-dev/template.config.json ships a placeholder deploying_iam_user ("<your 4dn-dcic IAM
  # username>"); set the real value before any apply.
  deploying_iam_user = "XXX: ENTER VALUE"
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "fourfront-prod-643366669028"
    scope      = "env"
    env        = "fourfront-production-blue"
    color      = "blue"
  }
}

module "appconfig" {
  source              = "../../../../modules/appconfig"
  env_name            = local.env_name
  deployment_paradigm = "standalone"
  deploying_iam_user  = local.deploying_iam_user
  global_env_bucket   = "foursight-prod-envs" # shared by both colors (plan §1.2)
  tags                = local.common_tags
}

# --- DEFERRED in this PR (see terraform/OWNERSHIP.md + terraform/README.md) ---
# module "datastore_slim" { source = "../../../../modules/datastore-slim" ... } # legacy ES 6.8 variant — NOT YET IMPLEMENTED
#   # network wiring would come from the shared network-data root:
#   #   private_subnet_ids = data.terraform_remote_state.shared.outputs.private_subnet_ids   (etc.)
# module "ecs_app"        { source = "../../../../modules/ecs-app" ... }        # fourfront_ecs.py — NOT YET IMPLEMENTED
