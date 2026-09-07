# ============================================================================================
# smaht-prod (865557043974) / env production — ENV root (env-scoped modules; plan §1.1, §2.4).
# ============================================================================================

provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = ["865557043974"]
  default_tags {
    tags = local.common_tags
  }
}

locals {
  env_name           = "production"
  deploying_iam_user = "arn:aws:iam::865557043974:user/david.michaels"
  common_tags = {
    project    = "c4"
    managed_by = "terraform"
    account    = "smaht-prod-865557043974"
    scope      = "env"
    env        = "production"
  }
}

data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = "4dn-cloud-infra-tf-state-865557043974"
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
  bucket_names        = module.datastore.bucket_names
  s3_bucket_org       = "kmp" # smaht-prod config: s3.bucket.org (does not affect bucket names today)
  s3_encrypt_key_id   = "9777cd71-4b5b-44b7-a8a0-de107c667c64"
  tags                = local.common_tags
}

module "datastore" {
  source                = "../../../../modules/datastore"
  rds_postgres_version  = var.rds_postgres_version
  bucket_name_overrides = var.bucket_name_overrides
  env_name              = local.env_name
  deployment_paradigm   = "standalone"

  private_subnet_ids      = data.terraform_remote_state.shared.outputs.private_subnet_ids
  db_security_group_id    = data.terraform_remote_state.shared.outputs.db_security_group_id
  https_security_group_id = data.terraform_remote_state.shared.outputs.https_security_group_id

  iam_s3_federator_user_arn = data.terraform_remote_state.shared.outputs.iam_s3_federator_user_arn
  iam_ecs_assumed_role_arn  = data.terraform_remote_state.shared.outputs.iam_ecs_assumed_role_arn
  deploying_iam_user_arn    = local.deploying_iam_user

  # smaht-prod config sizing
  s3_bucket_encryption  = true
  rds_instance_class    = "db.t3.medium" # rds.instance_size
  rds_allocated_storage = 50             # rds.storage_size
  rds_availability_zone = "us-east-1a"   # rds.az
  es_data_node_type     = "c5.large.elasticsearch"
  es_volume_size        = 50
  tags                  = local.common_tags
}

module "redis" {
  source                        = "../../../../modules/redis"
  env_name                      = local.env_name
  private_subnet_ids            = data.terraform_remote_state.shared.outputs.private_subnet_ids
  application_security_group_id = data.terraform_remote_state.shared.outputs.application_security_group_id
  tags                          = local.common_tags
}

# Implemented modules; account wiring awaits discovered identities/names and authorized adoption.
# module "ecs_app"   { source = "../../../../modules/ecs-app" ... }
# module "codebuild" { source = "../../../../modules/codebuild" ... }
# module "sentieon"  { source = "../../../../modules/ec2-service" service = "sentieon" ... }
