# SAME output names as modules/network for the Application VPC, so SRCE env-scoped modules could
# consume it interchangeably. DB/Compute VPC ids are exposed additively.

output "vpc_id" {
  value       = data.aws_vpc.application.id
  description = "SRCE Application VPC id."
}
output "vpc_cidr" {
  value       = data.aws_vpc.application.cidr_block
  description = "SRCE Application VPC CIDR."
}
output "private_subnet_ids" {
  value       = [for id in var.application_private_subnet_ids : data.aws_subnet.application_private[id].id]
  description = "Application VPC private subnet ids, in the order supplied."
}
output "public_subnet_ids" {
  value       = [for id in var.application_public_subnet_ids : data.aws_subnet.application_public[id].id]
  description = "Application VPC public subnet ids, in the order supplied."
}
output "db_vpc_id" {
  value       = length(data.aws_vpc.db) > 0 ? data.aws_vpc.db[0].id : null
  description = "SRCE Database VPC id."
}
output "db_vpc_cidr" {
  value       = length(data.aws_vpc.db) > 0 ? data.aws_vpc.db[0].cidr_block : null
  description = "SRCE Database VPC CIDR."
}
output "db_subnet_ids" {
  value       = var.db_subnet_ids
  description = "SRCE Database VPC subnet ids (pass-through)."
}
output "compute_vpc_id" {
  value       = length(data.aws_vpc.compute) > 0 ? data.aws_vpc.compute[0].id : null
  description = "SRCE Compute VPC id."
}
output "compute_vpc_cidr" {
  value       = length(data.aws_vpc.compute) > 0 ? data.aws_vpc.compute[0].cidr_block : null
  description = "SRCE Compute VPC CIDR."
}
output "compute_subnet_ids" {
  value       = var.compute_subnet_ids
  description = "SRCE Compute VPC subnet ids (pass-through)."
}
