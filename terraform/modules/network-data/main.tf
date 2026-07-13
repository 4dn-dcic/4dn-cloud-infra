# Read-only lookups over the unmanaged legacy VPC. NO resource blocks by design (plan §3 Phase 1b:
# "Do not import any of it — Terraform must never believe it owns IT-managed networking").

data "aws_vpc" "this" {
  id = var.fourfront_vpc_id
}

data "aws_subnet" "this" {
  for_each = toset(var.fourfront_subnet_ids)
  id       = each.value
}

data "aws_security_group" "rds" {
  id = var.fourfront_rds_sg_id
}

data "aws_security_group" "https" {
  id = var.fourfront_https_sg_id
}

data "aws_security_group" "application" {
  count = var.fourfront_application_sg_id == null ? 0 : 1
  id    = var.fourfront_application_sg_id
}
