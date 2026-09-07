# ============================================================================================
# fourfront-prod (643366669028) / env fourfront-production-BLUE — ENV root.
# The 4dn blue/green pair is realized as two STANDALONE env roots (blue + green), both sharing the
# account's shared/ root (network-data) — plan §1.2 point 3, §2.4, §5.1.
#
# Wired today: appconfig. Native datastore (variant=slim) and ecs-app (app_kind=ff) are
# implemented, but account wiring/adoption requires discovery; see terraform/PARITY.md.
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

# Account wiring remains gated on physical-resource and consumer discovery:
# module "datastore" { source = "../../../../modules/datastore" ... } # variant = "slim"
# module "ecs_app"   { source = "../../../../modules/ecs-app" ... }   # app_kind = "ff"
# Consume the existing network-data shared outputs; do not create/import the legacy VPC.
