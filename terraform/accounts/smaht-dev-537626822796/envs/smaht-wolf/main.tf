# ============================================================================================
# smaht-dev (537626822796) / env smaht-wolf — ENV root (env-scoped modules; plan §1.1, §2.4).
# Reads the account's shared/ state for VPC/IAM/ECR/Logging values — the Terraform analogue of the
# CFN --parameter-overrides + Fn::ImportValue contract (plan §5.2).
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["537626822796"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  env_name           = "smaht-wolf"
  deploying_iam_user = "arn:aws:iam::537626822796:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_5c5b330c7fb5d354"
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "smaht-dev-537626822796"
    scope      = "env"
    env        = "smaht-wolf"
  }
}

# Sibling shared-root state (same account bucket) — the cross-scope reference (plan §4.1, §5.2).
data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = "4dn-cloud-infra-tf-state-537626822796"
    key    = "shared/shared.tfstate"
    region = "us-east-1"
  }
}

variable "rds_postgres_version" {
  type    = string
  default = "17.6"
}
variable "bucket_name_overrides" {
  type    = map(string)
  default = {}
}

module "appconfig" {
  source              = "../../../../modules/appconfig"
  env_name            = local.env_name
  deployment_paradigm = "standalone"
  deploying_iam_user  = local.deploying_iam_user
  global_env_bucket   = "smaht-wolf-foursight-envs"
  bucket_names        = module.datastore.bucket_names
  s3_encrypt_key_id   = "27d040a3-ead1-4f5a-94ce-0fa6e7f84a95"
  tags                = local.common_tags
}

module "datastore" {
  source                = "../../../../modules/datastore"
  rds_postgres_version  = var.rds_postgres_version
  bucket_name_overrides = var.bucket_name_overrides
  env_name              = local.env_name
  deployment_paradigm   = "standalone"

  # network wiring from the shared root
  private_subnet_ids      = data.terraform_remote_state.shared.outputs.private_subnet_ids
  db_security_group_id    = data.terraform_remote_state.shared.outputs.db_security_group_id
  https_security_group_id = data.terraform_remote_state.shared.outputs.https_security_group_id

  # IAM wiring for the KMS key policy
  iam_s3_federator_user_arn = data.terraform_remote_state.shared.outputs.iam_s3_federator_user_arn
  iam_ecs_assumed_role_arn  = data.terraform_remote_state.shared.outputs.iam_ecs_assumed_role_arn
  deploying_iam_user_arn    = local.deploying_iam_user

  s3_bucket_encryption = true # smaht-wolf config: s3.bucket.encryption = true
  rds_name             = "rds-smaht-wolf"
  tags                 = local.common_tags
}

module "redis" {
  source                        = "../../../../modules/redis"
  env_name                      = local.env_name
  private_subnet_ids            = data.terraform_remote_state.shared.outputs.private_subnet_ids
  application_security_group_id = data.terraform_remote_state.shared.outputs.application_security_group_id
  tags                          = local.common_tags
}

# Modules implemented; wiring awaits discovered physical names and an authorized adoption plan.
# See terraform/examples/srce/main.tf for the typed producer/consumer contract, not account guesses.
# module "ecs_app"   { source = "../../../../modules/ecs-app" ... }
# module "codebuild" { source = "../../../../modules/codebuild" ... }
