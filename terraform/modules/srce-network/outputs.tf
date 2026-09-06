output "vpc_id" { value = var.application_vpc_id }
output "vpc_cidr" { value = var.application_cidr }
output "private_subnet_ids" { value = var.application_private_subnet_ids }
output "public_subnet_ids" { value = var.application_public_subnet_ids }
output "db_vpc_id" { value = var.db_vpc_id }
output "db_vpc_cidr" { value = var.db_cidr }
output "db_subnet_ids" { value = var.db_subnet_ids }
output "compute_vpc_id" { value = var.compute_vpc_id }
output "compute_vpc_cidr" { value = var.compute_cidr }
output "compute_subnet_ids" { value = var.compute_subnet_ids }
output "application_security_group_id" { value = aws_security_group.this["app_application"].id }
output "db_security_group_id" { value = aws_security_group.this["app_db"].id }
output "https_security_group_id" { value = aws_security_group.this["app_https"].id }
output "application_network" {
  value = {
    vpc_id                        = var.application_vpc_id, cidr_block = var.application_cidr
    private_subnet_ids            = var.application_private_subnet_ids, public_subnet_ids = var.application_public_subnet_ids
    application_security_group_id = aws_security_group.this["app_application"].id
  }
}
output "database_network" {
  value = {
    vpc_id                        = var.db_vpc_id, private_subnet_ids = var.db_subnet_ids
    db_security_group_id          = aws_security_group.this["db_db"].id
    https_security_group_id       = aws_security_group.this["db_https"].id
    application_security_group_id = aws_security_group.this["db_application"].id
  }
}
output "compute_network" {
  value = { vpc_id = var.compute_vpc_id, private_subnet_ids = var.compute_subnet_ids, application_security_group_id = aws_security_group.this["compute_application"].id }
}
