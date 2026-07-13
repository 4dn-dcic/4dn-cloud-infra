# Network module — faithful port of src/parts/network.py (C4Network, SHARING='ecosystem').
#
# Scope: ECOSYSTEM-shared -> account shared/ root ONLY (one VPC per account). The 4dn/fourfront
# account does NOT use this module — its VPC is unmanaged legacy infra (see modules/network-data).
#
# Structure mirrors C4Network.build_template: VPC + IGW, route tables, subnets (A..F limited by
# subnet_pair_count), NAT gateway in public subnet A, three security groups with their rules, and
# the 10 interface + 2 gateway VPC endpoints. Bastion host (network.py:729) is intentionally NOT
# ported (defined-but-optional; plan §6.9) — enable separately if ever needed.

locals {
  # Fixed subnet layout from C4NetworkExports.SUBNET_CONFIG_INFO (network.py:25-50).
  subnet_config = {
    PrivateSubnetA = { cidr = "10.0.0.0/20", az = "${var.region}a", kind = "private", pair = 1 }
    PublicSubnetA  = { cidr = "10.0.16.0/20", az = "${var.region}a", kind = "public", pair = 1 }
    PrivateSubnetB = { cidr = "10.0.32.0/20", az = "${var.region}b", kind = "private", pair = 2 }
    PublicSubnetB  = { cidr = "10.0.48.0/20", az = "${var.region}b", kind = "public", pair = 2 }
    PrivateSubnetC = { cidr = "10.0.64.0/20", az = "${var.region}c", kind = "private", pair = 3 }
    PublicSubnetC  = { cidr = "10.0.80.0/20", az = "${var.region}c", kind = "public", pair = 3 }
    PrivateSubnetD = { cidr = "10.0.96.0/20", az = "${var.region}d", kind = "private", pair = 4 }
    PublicSubnetD  = { cidr = "10.0.112.0/20", az = "${var.region}d", kind = "public", pair = 4 }
    PrivateSubnetE = { cidr = "10.0.128.0/20", az = "${var.region}e", kind = "private", pair = 5 }
    PublicSubnetE  = { cidr = "10.0.144.0/20", az = "${var.region}e", kind = "public", pair = 5 }
    PrivateSubnetF = { cidr = "10.0.160.0/20", az = "${var.region}f", kind = "private", pair = 6 }
    PublicSubnetF  = { cidr = "10.0.176.0/20", az = "${var.region}f", kind = "public", pair = 6 }
  }

  private_subnets = { for k, v in local.subnet_config : k => v if v.kind == "private" && v.pair <= var.subnet_pair_count }
  public_subnets  = { for k, v in local.subnet_config : k => v if v.kind == "public" && v.pair <= var.subnet_pair_count }

  # First public/private subnet keys (pair 1) — NAT lives in public A; endpoints in private A.
  first_public_key  = "PublicSubnetA"
  first_private_key = "PrivateSubnetA"

  # 10 interface + 2 gateway VPC endpoints (network.py:185-209).
  interface_endpoints = {
    sqs            = "com.amazonaws.${var.region}.sqs"
    ecrapi         = "com.amazonaws.${var.region}.ecr.api"
    ecrdkr         = "com.amazonaws.${var.region}.ecr.dkr"
    secretsmanager = "com.amazonaws.${var.region}.secretsmanager"
    ssm            = "com.amazonaws.${var.region}.ssm"
    logs           = "com.amazonaws.${var.region}.logs"
    ec2            = "com.amazonaws.${var.region}.ec2"
    ebs            = "com.amazonaws.${var.region}.ebs"
    lambda         = "com.amazonaws.${var.region}.lambda"
    states         = "com.amazonaws.${var.region}.states"
  }
  gateway_endpoints = {
    dynamodb = "com.amazonaws.${var.region}.dynamodb"
    s3       = "com.amazonaws.${var.region}.s3"
  }
}

# --- VPC + Internet Gateway ---------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.cidr_block
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_internet_gateway" "main" {
  # aws_internet_gateway with vpc_id subsumes the CFN VPCGatewayAttachment (network.py:313).
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

# --- VPC flow logs (SEC-9; network.py:249-311) --------------------------------------------
resource "aws_cloudwatch_log_group" "flow_log" {
  count             = var.flow_logs_enabled ? 1 : 0
  name              = coalesce(var.flow_log_group_name, "${var.name_prefix}-vpc-flow-logs")
  retention_in_days = var.flow_logs_retention_days
  tags              = var.tags

  # SAFETY GATE — faithful to network.py:257-258 DeletionPolicy=Retain + UpdateReplacePolicy=Retain.
  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "flow_log_assume" {
  count = var.flow_logs_enabled ? 1 : 0
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "flow_log_delivery" {
  count = var.flow_logs_enabled ? 1 : 0
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:DescribeLogGroups",
      "logs:DescribeLogStreams",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "flow_log" {
  count              = var.flow_logs_enabled ? 1 : 0
  name               = "${var.name_prefix}-vpc-flow-log-delivery"
  assume_role_policy = data.aws_iam_policy_document.flow_log_assume[0].json
  tags               = var.tags

  inline_policy {
    name   = "VPCFlowLogDelivery"
    policy = data.aws_iam_policy_document.flow_log_delivery[0].json
  }
}

resource "aws_flow_log" "main" {
  count                = var.flow_logs_enabled ? 1 : 0
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.flow_log[0].arn
  iam_role_arn         = aws_iam_role.flow_log[0].arn
  tags                 = var.tags
}

# --- Route tables -------------------------------------------------------------------------
resource "aws_route_table" "main" {
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-main-rt" })
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-private-rt" })
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-public-rt" })
}

# --- Subnets ------------------------------------------------------------------------------
resource "aws_subnet" "private" {
  for_each          = local.private_subnets
  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az
  tags              = merge(var.tags, { Name = "${var.name_prefix}-${each.key}" })
}

resource "aws_subnet" "public" {
  for_each          = local.public_subnets
  vpc_id            = aws_vpc.main.id
  cidr_block        = each.value.cidr
  availability_zone = each.value.az
  tags              = merge(var.tags, { Name = "${var.name_prefix}-${each.key}" })
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

# --- NAT gateway (in public subnet A) -----------------------------------------------------
resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-nat-eip" })
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[local.first_public_key].id
  tags          = merge(var.tags, { Name = "${var.name_prefix}-nat" })

  # network.py:341 DependsOn=eip — explicit paper trail (plan §6.7).
  depends_on = [aws_eip.nat]
}

resource "aws_route" "internet_gateway" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route" "nat_gateway" {
  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main.id
}

# --- Security groups ----------------------------------------------------------------------
resource "aws_security_group" "db" {
  name        = lookup(var.security_group_name_overrides, "db", "${var.name_prefix}-DBSecurityGroup")
  description = "allows database access on a port range"
  vpc_id      = aws_vpc.main.id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-DBSecurityGroup" })
}

resource "aws_security_group" "https" {
  name        = lookup(var.security_group_name_overrides, "https", "${var.name_prefix}-HTTPSSecurityGroup")
  description = "allows https-only web access on port 443"
  vpc_id      = aws_vpc.main.id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-HTTPSSecurityGroup" })
}

resource "aws_security_group" "application" {
  name        = lookup(var.security_group_name_overrides, "application", "${var.name_prefix}-ApplicationSecurityGroup")
  description = "allows access needed by Application"
  vpc_id      = aws_vpc.main.id
  tags        = merge(var.tags, { Name = "${var.name_prefix}-ApplicationSecurityGroup" })
}

# DB rules (network.py:514-542): tcp 5400-5499 in/out within the VPC CIDR.
resource "aws_security_group_rule" "db_inbound" {
  type              = "ingress"
  security_group_id = aws_security_group.db.id
  protocol          = "tcp"
  from_port         = var.db_port_low
  to_port           = var.db_port_high
  cidr_blocks       = [var.cidr_block]
  description       = "allows database access on tcp ports 54xx"
}

resource "aws_security_group_rule" "db_outbound" {
  type              = "egress"
  security_group_id = aws_security_group.db.id
  protocol          = "tcp"
  from_port         = var.db_port_low
  to_port           = var.db_port_high
  cidr_blocks       = [var.cidr_block]
  description       = "allows outbound traffic to tcp 54xx"
}

# HTTPS rules (network.py:568-596): 443 in from CIDR, 443 out to anywhere.
resource "aws_security_group_rule" "https_inbound" {
  type              = "ingress"
  security_group_id = aws_security_group.https.id
  protocol          = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_blocks       = [var.cidr_block]
  description       = "allows inbound traffic on tcp port 443"
}

resource "aws_security_group_rule" "https_outbound" {
  type              = "egress"
  security_group_id = aws_security_group.https.id
  protocol          = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "allows outbound traffic on tcp port 443"
}

# Application rules (network.py:624-727): 443/80 in(CIDR)+out(any), 123/udp in(CIDR)+out(any),
# 22 in(CIDR)+out(CIDR), 6379 in(CIDR)+out(CIDR).
locals {
  application_rules = {
    https_in  = { type = "ingress", proto = "tcp", from = 443, to = 443, cidr = var.cidr_block, desc = "allows inbound traffic on tcp port 443" }
    https_out = { type = "egress", proto = "tcp", from = 443, to = 443, cidr = "0.0.0.0/0", desc = "allows outbound traffic on tcp port 443" }
    web_in    = { type = "ingress", proto = "tcp", from = 80, to = 80, cidr = var.cidr_block, desc = "allows inbound traffic on tcp port 80" }
    web_out   = { type = "egress", proto = "tcp", from = 80, to = 80, cidr = "0.0.0.0/0", desc = "allows outbound traffic on tcp port 80" }
    ntp_in    = { type = "ingress", proto = "udp", from = 123, to = 123, cidr = var.cidr_block, desc = "allows inbound traffic on udp port 123" }
    ntp_out   = { type = "egress", proto = "udp", from = 123, to = 123, cidr = "0.0.0.0/0", desc = "allows outbound traffic on udp port 123" }
    ssh_in    = { type = "ingress", proto = "tcp", from = 22, to = 22, cidr = var.cidr_block, desc = "allows inbound traffic on tcp port 22" }
    ssh_out   = { type = "egress", proto = "tcp", from = 22, to = 22, cidr = var.cidr_block, desc = "allows outbound traffic on tcp port 22" }
    redis_in  = { type = "ingress", proto = "tcp", from = 6379, to = 6379, cidr = var.cidr_block, desc = "allows inbound traffic on tcp port 6379" }
    redis_out = { type = "egress", proto = "tcp", from = 6379, to = 6379, cidr = var.cidr_block, desc = "allows outbound traffic on tcp port 6379" }
  }
}

resource "aws_security_group_rule" "application" {
  for_each          = local.application_rules
  type              = each.value.type
  security_group_id = aws_security_group.application.id
  protocol          = each.value.proto
  from_port         = each.value.from
  to_port           = each.value.to
  cidr_blocks       = [each.value.cidr]
  description       = each.value.desc
}

# --- VPC endpoints (network.py:764-801) ---------------------------------------------------
resource "aws_vpc_endpoint" "interface" {
  for_each            = local.interface_endpoints
  vpc_id              = aws_vpc.main.id
  service_name        = each.value
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.private[local.first_private_key].id]
  security_group_ids  = [aws_security_group.application.id]
  tags                = merge(var.tags, { Name = "${var.name_prefix}-${each.key}-endpoint" })
}

resource "aws_vpc_endpoint" "gateway" {
  for_each          = local.gateway_endpoints
  vpc_id            = aws_vpc.main.id
  service_name      = each.value
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = merge(var.tags, { Name = "${var.name_prefix}-${each.key}-endpoint" })
}
