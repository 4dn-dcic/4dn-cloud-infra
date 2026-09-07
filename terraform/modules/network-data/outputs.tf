# SAME output names as modules/network so downstream env-scoped modules are source-agnostic.

output "vpc_id" {
  value       = data.aws_vpc.this.id
  description = "Unmanaged VPC id."
}

output "vpc_cidr" {
  value       = data.aws_vpc.this.cidr_block
  description = "Unmanaged VPC CIDR (e.g. 172.31.0.0/16)."
}

output "private_subnet_ids" {
  value       = [for id in var.fourfront_subnet_ids : data.aws_subnet.this[id].id]
  description = "Pre-existing subnet ids, in the order supplied."
}

output "public_subnet_ids" {
  value       = []
  description = "Not modeled for the legacy VPC (no public subnets are injected via config)."
}

output "db_security_group_id" {
  value       = data.aws_security_group.rds.id
  description = "Legacy RDS security-group id (maps to network db_security_group_id)."
}

output "https_security_group_id" {
  value       = data.aws_security_group.https.id
  description = "Legacy HTTPS security-group id."
}

output "application_security_group_id" {
  value       = var.fourfront_application_sg_id == null ? data.aws_security_group.https.id : data.aws_security_group.application[0].id
  description = "Application SG id; falls back to the HTTPS SG when not separately supplied."
}
