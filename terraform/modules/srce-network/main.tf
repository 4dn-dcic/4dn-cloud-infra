# Read-only lookups over the IT-provided SRCE VPCs. NO resource blocks — Terraform must never
# believe it owns IT-managed networking (same discipline as modules/network-data).

data "aws_vpc" "application" {
  id = var.application_vpc_id
}

data "aws_subnet" "application_private" {
  for_each = toset(var.application_private_subnet_ids)
  id       = each.value
}

data "aws_subnet" "application_public" {
  for_each = toset(var.application_public_subnet_ids)
  id       = each.value
}

data "aws_vpc" "db" {
  count = var.db_vpc_id == null ? 0 : 1
  id    = var.db_vpc_id
}

data "aws_vpc" "compute" {
  count = var.compute_vpc_id == null ? 0 : 1
  id    = var.compute_vpc_id
}
