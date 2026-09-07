# Re-export the legacy-VPC data-source values so env roots (blue/green) can read them via
# data.terraform_remote_state. Uses the SAME names as the smaht shared roots so env-scoped modules
# are source-agnostic (network vs network-data).
output "vpc_id" { value = module.network_data.vpc_id }
output "vpc_cidr" { value = module.network_data.vpc_cidr }
output "private_subnet_ids" { value = module.network_data.private_subnet_ids }
output "db_security_group_id" { value = module.network_data.db_security_group_id }
output "https_security_group_id" { value = module.network_data.https_security_group_id }
output "application_security_group_id" { value = module.network_data.application_security_group_id }
