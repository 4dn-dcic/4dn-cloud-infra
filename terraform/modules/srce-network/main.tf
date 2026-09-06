# IT owns all three VPCs, subnets, routes, NAT/endpoints and centralized logging/CloudTrail.
# This module owns ONLY the security groups/rules of srce-network{,-db,-compute}.
locals {
  groups = {
    app_db              = { vpc = var.application_vpc_id, description = "allows database access on a port range" }
    app_https           = { vpc = var.application_vpc_id, description = "allows https-only web access on port 443" }
    app_application     = { vpc = var.application_vpc_id, description = "allows access needed by Application" }
    db_db               = { vpc = var.db_vpc_id, description = "allows database access on a port range" }
    db_https            = { vpc = var.db_vpc_id, description = "allows https-only web access on port 443" }
    db_application      = { vpc = var.db_vpc_id, description = "allows access needed by Application" }
    compute_application = { vpc = var.compute_vpc_id, description = "allows access needed by Application" }
  }
  # [group, direction, protocol, from, to, CIDR]. Includes the standard Application shell rules.
  rules = concat([
    ["app_db", "ingress", "tcp", 5400, 5499, var.application_cidr],
    ["app_db", "egress", "tcp", 5400, 5499, var.application_cidr],
    ["app_https", "ingress", "tcp", 443, 443, var.application_cidr],
    ["app_https", "egress", "tcp", 443, 443, "0.0.0.0/0"]
    ], concat([for port in [443, 80, 123, 22, 6379] : [
      ["app_application", "ingress", port == 123 ? "udp" : "tcp", port, port, var.application_cidr],
      ["app_application", "egress", port == 123 ? "udp" : "tcp", port, port, contains([443, 80, 123], port) ? "0.0.0.0/0" : var.application_cidr]
    ]]...), [
    ["app_db", "ingress", "tcp", 5400, 5499, var.db_cidr],
    ["app_db", "egress", "tcp", 5400, 5499, var.db_cidr],
    ["app_application", "ingress", "tcp", 6379, 6379, var.db_cidr],
    ["app_application", "egress", "tcp", 6379, 6379, var.db_cidr],
    ["app_application", "egress", "tcp", 443, 443, var.db_cidr],
    ["app_application", "egress", "tcp", 443, 443, var.compute_cidr],
    ["app_application", "ingress", "tcp", 443, 443, var.compute_cidr],
    ["app_application", "ingress", "tcp", 8990, 8990, var.compute_cidr],
    ["db_db", "ingress", "tcp", 5400, 5499, var.application_cidr],
    ["db_db", "egress", "tcp", 5400, 5499, var.application_cidr],
    ["db_application", "ingress", "tcp", 6379, 6379, var.application_cidr],
    ["db_application", "egress", "tcp", 6379, 6379, var.application_cidr],
    ["db_https", "ingress", "tcp", 443, 443, var.application_cidr],
    ["compute_application", "ingress", "tcp", 443, 443, var.application_cidr],
    ["compute_application", "ingress", "tcp", 22, 22, var.application_cidr],
    ["compute_application", "egress", "tcp", 443, 443, var.application_cidr],
    ["compute_application", "egress", "tcp", 8990, 8990, var.application_cidr]
  ])
  subnet_sets = [var.application_private_subnet_ids, var.application_public_subnet_ids, var.db_subnet_ids, var.compute_subnet_ids]
}
resource "aws_security_group" "this" {
  for_each    = local.groups
  name        = lookup(var.security_group_name_overrides, each.key, null)
  vpc_id      = each.value.vpc
  description = each.value.description
  tags        = var.tags
  lifecycle {
    precondition {
      condition     = length(distinct([var.application_vpc_id, var.db_vpc_id, var.compute_vpc_id])) == 3 && alltrue([for s in local.subnet_sets : length(s) >= 2 && length(s) <= 6]) && length(distinct(flatten(local.subnet_sets))) == length(flatten(local.subnet_sets))
      error_message = "Supply three distinct IT VPCs and disjoint subnet sets (2-6 each). IDs do not prove live membership/AZ/routing."
    }
  }
}
resource "aws_security_group_rule" "this" {
  for_each          = { for r in local.rules : join("_", r) => r }
  security_group_id = aws_security_group.this[each.value[0]].id
  type              = each.value[1]
  protocol          = each.value[2]
  from_port         = tonumber(each.value[3])
  to_port           = tonumber(each.value[4])
  cidr_blocks       = [each.value[5]]
}
# EC2's default egress survives CFN's separate AWS::EC2::SecurityGroupEgress resources.
# Terraform removes it on group creation, so carry it explicitly, not an accidental restriction.
resource "aws_security_group_rule" "default_egress" {
  for_each          = local.groups
  security_group_id = aws_security_group.this[each.key].id
  type              = "egress"
  protocol          = "-1"
  from_port         = 0
  to_port           = 0
  cidr_blocks       = ["0.0.0.0/0"]
}
