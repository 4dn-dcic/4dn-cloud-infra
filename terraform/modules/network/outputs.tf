# Outputs mirror C4NetworkExports (network.py:21-92). These are the values downstream env-scoped
# modules consume across state (data.terraform_remote_state.network.outputs.*), the direct
# analogue of today's Fn::ImportValue on the shared network stack (plan §5.2). NOTE: modules/
# network-data (the 4dn legacy VPC) exposes the SAME output names so consumers are interchangeable.

output "vpc_id" {
  description = "VPC id. Mirrors C4NetworkExports.VPC."
  value       = aws_vpc.main.id
}

output "vpc_cidr" {
  description = "VPC CIDR block."
  value       = aws_vpc.main.cidr_block
}

output "private_subnet_ids" {
  description = "Private subnet ids, ordered A..N. Mirrors C4NetworkExports.PRIVATE_SUBNETS."
  value       = [for k in sort(keys(aws_subnet.private)) : aws_subnet.private[k].id]
}

output "public_subnet_ids" {
  description = "Public subnet ids, ordered A..N. Mirrors C4NetworkExports.PUBLIC_SUBNETS."
  value       = [for k in sort(keys(aws_subnet.public)) : aws_subnet.public[k].id]
}

output "db_security_group_id" {
  description = "DB security-group id. Mirrors C4NetworkExports.DB_SECURITY_GROUP."
  value       = aws_security_group.db.id
}

output "https_security_group_id" {
  description = "HTTPS security-group id. Mirrors C4NetworkExports.HTTPS_SECURITY_GROUP."
  value       = aws_security_group.https.id
}

output "application_security_group_id" {
  description = "Application security-group id. Mirrors C4NetworkExports.APPLICATION_SECURITY_GROUP."
  value       = aws_security_group.application.id
}
