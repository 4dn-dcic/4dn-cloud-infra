# ENV root wiring example, not an account deployment. Shared resources are owned once by the
# sibling shared root. Supply its reviewed outputs as var.shared; never create a second owner.
variable "env_name" { type = string }
variable "account_id" { type = string }
variable "deploying_iam_user_arn" { type = string }
variable "rds_postgres_version" {
  type    = string
  default = "17.6"
}
variable "shared" {
  type = object({
    application_network   = object({ vpc_id = string, cidr_block = string, private_subnet_ids = list(string), public_subnet_ids = list(string), application_security_group_id = string })
    database_network      = object({ private_subnet_ids = list(string), db_security_group_id = string, https_security_group_id = string, application_security_group_id = string })
    compute_subnet_ids    = list(string)
    ecs_role_arn          = string
    s3_federator_arn      = string
    portal_repository_url = string
    application_log_group = string
    dockerhub_secret_arn  = string
    github_credential_arn = string
  })
}
variable "certificate_arn" {
  type    = string
  default = null
}
provider "aws" {
  region              = "us-east-1"
  allowed_account_ids = [var.account_id]
}
module "datastore" {
  source                    = "../../modules/datastore"
  variant                   = "srce"
  env_name                  = var.env_name
  rds_postgres_version      = var.rds_postgres_version
  private_subnet_ids        = var.shared.database_network.private_subnet_ids
  db_security_group_id      = var.shared.database_network.db_security_group_id
  https_security_group_id   = var.shared.database_network.https_security_group_id
  iam_s3_federator_user_arn = var.shared.s3_federator_arn
  iam_ecs_assumed_role_arn  = var.shared.ecs_role_arn
  deploying_iam_user_arn    = var.deploying_iam_user_arn
}
module "appconfig" {
  source             = "../../modules/appconfig"
  env_name           = var.env_name
  deploying_iam_user = var.deploying_iam_user_arn
  bucket_names       = module.datastore.bucket_names
}
module "ecs" {
  source                = "../../modules/ecs-app"
  env_name              = var.env_name
  app_kind              = "smaht"
  srce                  = true
  network               = var.shared.application_network
  certificate_arn       = var.certificate_arn
  ecs_role_arn          = var.shared.ecs_role_arn
  portal_repository_url = var.shared.portal_repository_url
  log_groups            = { standalone = var.shared.application_log_group }
  identities            = module.appconfig.gac_secret_names
  # Populate/reconcile the GAC BEFORE any later authorized ECS rollout.
}
module "codebuild" {
  source                   = "../../modules/codebuild"
  env_name                 = var.env_name
  app_kind                 = "smaht"
  account_id               = var.account_id
  srce_application_network = var.shared.application_network
  excluded_subnet_ids      = concat(var.shared.application_network.public_subnet_ids, var.shared.database_network.private_subnet_ids, var.shared.compute_subnet_ids)
  dockerhub_secret_arn     = var.shared.dockerhub_secret_arn
  falcon_secret_arns       = module.appconfig.falcon_secret_arns
  github_credential_arn    = var.shared.github_credential_arn
}
module "redis" {
  source                        = "../../modules/redis"
  env_name                      = var.env_name
  private_subnet_ids            = var.shared.database_network.private_subnet_ids
  application_security_group_id = var.shared.database_network.application_security_group_id
}
output "foursight_runtime" {
  description = "Metadata for the retained foursight-srce Chalice packaging path; never selects DB/Compute or reads secret values."
  value = {
    identity           = module.appconfig.foursight_secret_name
    subnet_ids         = var.shared.application_network.private_subnet_ids
    security_group_ids = [var.shared.application_network.application_security_group_id]
    package_group      = "foursight_smaht"
  }
}
