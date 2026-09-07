# Re-export shared values so env roots can read them via data.terraform_remote_state (plan §5.2).
output "vpc_id" { value = module.network.vpc_id }
output "private_subnet_ids" { value = module.network.private_subnet_ids }
output "public_subnet_ids" { value = module.network.public_subnet_ids }
output "db_security_group_id" { value = module.network.db_security_group_id }
output "https_security_group_id" { value = module.network.https_security_group_id }
output "application_security_group_id" { value = module.network.application_security_group_id }

output "iam_ecs_assumed_role_name" { value = module.iam.ecs_assumed_role_name }
output "iam_ecs_assumed_role_arn" { value = module.iam.ecs_assumed_role_arn }
output "iam_s3_federator_user_arn" { value = module.iam.s3_federator_user_arn }
output "iam_instance_profile_name" { value = module.iam.instance_profile_name }

output "ecr_repository_urls" { value = module.ecr.repository_urls }
output "application_log_group" { value = module.logging.application_log_group }
output "dockerhub_credentials_arn" { value = module.shared_secrets.dockerhub_credentials_arn }
