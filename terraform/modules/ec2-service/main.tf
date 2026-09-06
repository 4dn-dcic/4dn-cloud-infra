locals {
  license    = var.service == "sentieon"
  identifier = { sentieon = "Sentieon", higlass = "Higlass", jupyterhub = "JupyterHub" }[var.service]
  admin_cidr = coalesce(var.admin_cidr, local.license ? var.network.cidr_block : "0.0.0.0/0")
  # [direction, protocol, from, to, CIDR]. CFN separate rules keep EC2 default egress.
  rules = concat([
    ["ingress", "tcp", 22, 22, local.admin_cidr], ["egress", "tcp", 22, 22, local.admin_cidr]
    ], local.license ? concat([
      ["ingress", "tcp", 8990, 8990, var.network.cidr_block],
      ["egress", "tcp", 443, 443, "52.89.132.242/32"],
      ["ingress", "icmp", -1, -1, var.network.cidr_block],
      ["egress", "icmp", -1, -1, var.network.cidr_block]
    ], var.compute_cidr == null ? [] : [["ingress", "tcp", 8990, 8990, var.compute_cidr]]) : [
    ["ingress", "tcp", 80, 80, var.network.cidr_block], ["egress", "tcp", 80, 80, "0.0.0.0/0"],
    ["ingress", "tcp", 443, 443, var.network.cidr_block], ["egress", "tcp", 443, 443, "0.0.0.0/0"]
  ])
}
resource "aws_security_group" "instance" {
  name        = lookup(var.name_overrides, "security_group", null)
  description = local.license ? "allows access needed by Sentieon License Server" : "allows access needed by ${local.identifier}"
  vpc_id      = var.network.vpc_id
  tags        = var.tags
}
resource "aws_security_group_rule" "instance" {
  for_each          = { for r in local.rules : join("_", r) => r }
  security_group_id = aws_security_group.instance.id
  type              = each.value[0]
  protocol          = each.value[1]
  from_port         = tonumber(each.value[2])
  to_port           = tonumber(each.value[3])
  cidr_blocks       = [each.value[4]]
}
resource "aws_security_group_rule" "default_egress" {
  security_group_id = aws_security_group.instance.id
  type              = "egress"
  protocol          = "-1"
  from_port         = 0
  to_port           = 0
  cidr_blocks       = ["0.0.0.0/0"]
}
resource "aws_instance" "this" {
  ami                         = var.ami
  instance_type               = coalesce(var.instance_type, local.license ? "t2.nano" : "c5.large")
  key_name                    = var.ssh_key
  subnet_id                   = local.license ? var.network.public_subnet_ids[0] : var.network.private_subnet_ids[0]
  associate_public_ip_address = true
  vpc_security_group_ids      = [aws_security_group.instance.id]
  user_data_base64            = local.license ? null : base64encode(file("${path.module}/${var.service}.sh"))
  tags                        = merge({ Name = "${var.env_name}-${var.service}" }, var.tags)
}
resource "aws_security_group" "lb" {
  count       = local.license ? 0 : 1
  name        = lookup(var.name_overrides, "lb_security_group", null)
  description = "Web load balancer security group for ${local.identifier}."
  vpc_id      = var.network.vpc_id
  dynamic "ingress" {
    for_each = [80, 443]
    content {
      protocol    = "tcp"
      from_port   = ingress.value
      to_port     = ingress.value
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
  dynamic "egress" {
    for_each = [80, 443]
    content {
      protocol    = "tcp"
      from_port   = egress.value
      to_port     = egress.value
      cidr_blocks = [var.network.cidr_block]
    }
  }
  tags = var.tags
}
resource "aws_lb" "this" {
  count              = local.license ? 0 : 1
  name               = lookup(var.name_overrides, "lb", "${local.identifier}LoadBalancer")
  internal           = false
  load_balancer_type = "application"
  ip_address_type    = "ipv4"
  security_groups    = [aws_security_group.lb[0].id]
  subnets            = slice(var.network.public_subnet_ids, 0, 2)
  tags               = var.tags
}
resource "aws_lb_target_group" "this" {
  count       = local.license ? 0 : 1
  name        = lookup(var.name_overrides, "target", "TargetGroup${local.identifier}")
  port        = 80
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.network.vpc_id
  health_check {
    interval = 60
    path     = var.service == "higlass" ? "/api/v1/tilesets/" : "/health?format=json"
    protocol = "HTTP"
    timeout  = 10
    matcher  = "200"
  }
  tags = var.tags
}
# Preserve current auxiliary HTTP behavior. Portal TLS is implemented in ecs-app, not here.
# No automatic target attachment: current CFN explicitly leaves registration to the operator.
resource "aws_lb_listener" "this" {
  count             = local.license ? 0 : 1
  load_balancer_arn = aws_lb.this[0].arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this[0].arn
  }
}
