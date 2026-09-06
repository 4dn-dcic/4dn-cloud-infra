# Native ECS/ALB port of the complete standalone/Fourfront/blue-green contracts.
# SHARING: standalone -> env root; blue_green -> ecosystem root ONCE (not one per color).
locals {
  blue_green = var.deployment_paradigm == "blue_green"
  fourfront  = var.app_kind == "ff" && !local.blue_green && !var.srce
  tls        = var.certificate_arn != null && var.certificate_arn != ""
  colors     = toset(local.blue_green ? ["blue", "green"] : ["standalone"])
  task_types = local.fourfront ? ["portal", "indexer", "initial-deployment", "deployment"] : ["portal", "indexer", "ingester", "initial-deployment", "deployment"]
  sizes = merge({
    portal             = { cpu = local.fourfront ? "1024" : "4096", memory = local.fourfront ? "2048" : "8192" }
    indexer            = { cpu = "256", memory = "512" }
    ingester           = { cpu = "512", memory = "1024" }
    initial-deployment = { cpu = "1024", memory = "2048" }
    deployment         = { cpu = "1024", memory = "2048" }
  }, var.task_sizes)
  counts          = merge({ portal = local.fourfront || local.blue_green ? 8 : 2, indexer = 4, ingester = 1 }, var.desired_counts)
  container_names = { portal = local.blue_green ? "Portal" : "portal", indexer = "Indexer", ingester = "Ingester", initial-deployment = "DeploymentAction", deployment = "DeploymentAction" }
  tasks = { for t in flatten([for c in local.colors : [for kind in local.task_types : {
    key           = "${c}-${kind}", color = c, kind = kind
    prefix        = local.fourfront ? (kind == "deployment" ? "cgap-deployment" : "fourfront-${kind}") : "${var.app_kind}-${kind}"
    falcon_prefix = "${local.fourfront ? "fourfront" : var.app_kind}-${kind}${local.blue_green ? c : ""}-falcon"
  }]]) : t.key => t }
  services = { for k, t in local.tasks : k => t if contains(["portal", "indexer", "ingester"], t.kind) }
  log_options = { for k, t in local.tasks : k => {
    awslogs-group = var.log_groups[t.color], awslogs-region = var.region, awslogs-stream-prefix = t.prefix
  } }
  app_containers = { for k, t in local.tasks : k => merge({
    name             = local.container_names[t.kind]
    essential        = true
    image            = "${var.portal_repository_url}:${local.blue_green ? t.color : var.image_tag}"
    logConfiguration = { logDriver = "awslogs", options = local.log_options[k] }
    environment = concat([
      { name = "IDENTITY", value = var.identities[t.color] }
      ], contains(["initial-deployment", "deployment"], t.kind) ? [{ name = "INITIAL_DEPLOYMENT", value = t.kind == "initial-deployment" ? "TRUE" : "" }] : [], [
      { name = "application_type", value = t.kind == "initial-deployment" ? "deployment" : t.kind }
    ], local.fourfront || local.blue_green ? [{ name = "SQS_URL", value = "https://sqs.us-east-1.amazonaws.com/" }] : [])
    }, t.kind == "portal" ? { portMappings = [{ containerPort = var.web_worker_port }] } : {}, jsondecode(var.crowdstrike.enabled ? jsonencode({
      mountPoints = [{ sourceVolume = "crowdstrike-falcon-volume", containerPath = var.crowdstrike.mount_path, readOnly = true }]
      entryPoint  = var.crowdstrike.entrypoint
      dependsOn   = [{ containerName = "falcon-container", condition = "SUCCESS" }]
  }) : "{}")) }
  container_definitions = { for k, t in local.tasks : k => jsonencode(concat([local.app_containers[k]], var.crowdstrike.enabled ? [{
    name             = "falcon-container", essential = false, image = var.crowdstrike.sensor_image
    environment      = [{ name = "FALCONCTL_OPT_BACKEND", value = var.crowdstrike.backend }]
    secrets          = [{ name = "FALCONCTL_OPT_FALCONCTL_CID", valueFrom = var.crowdstrike.cid_secret_arn }]
    mountPoints      = [{ sourceVolume = "crowdstrike-falcon-volume", containerPath = var.crowdstrike.mount_path, readOnly = false }]
    logConfiguration = { logDriver = "awslogs", options = merge(local.log_options[k], { awslogs-stream-prefix = t.falcon_prefix }) }
  }] : [])) }
}
resource "aws_ecs_cluster" "this" {
  for_each = local.colors
  name     = lookup(var.name_overrides, "cluster-${each.key}", "${var.env_name}-${each.key}")
  tags     = var.tags
}
resource "aws_ecs_cluster_capacity_providers" "this" {
  for_each           = aws_ecs_cluster.this
  cluster_name       = each.value.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
}
resource "aws_ecs_task_definition" "this" {
  for_each                 = local.tasks
  family                   = lookup(var.name_overrides, "task-${each.key}", "${var.env_name}-${each.key}")
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  task_role_arn            = var.ecs_role_arn
  execution_role_arn       = var.ecs_role_arn
  cpu                      = local.sizes[each.value.kind].cpu
  memory                   = local.sizes[each.value.kind].memory
  container_definitions    = local.container_definitions[each.key]
  dynamic "volume" {
    for_each = var.crowdstrike.enabled ? [1] : []
    content { name = "crowdstrike-falcon-volume" }
  }
  tags = var.tags
}
resource "aws_security_group" "container" {
  description = "Container Security Group."
  vpc_id      = var.network.vpc_id
  ingress {
    protocol    = "tcp"
    from_port   = var.web_worker_port
    to_port     = var.web_worker_port
    cidr_blocks = [var.network.cidr_block]
  }
  # CFN leaves the EC2 default outbound rule intact; Terraform removes it unless explicit.
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}
resource "aws_security_group" "lb" {
  description = "Web load balancer security group."
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
  egress {
    protocol    = "-1"
    from_port   = 0
    to_port     = 0
    cidr_blocks = ["0.0.0.0/0"]
  }
  tags = var.tags
}
resource "aws_lb" "this" {
  for_each           = local.colors
  name               = lookup(var.name_overrides, "lb-${each.key}", "${var.env_name}${local.blue_green ? each.key : ""}")
  internal           = false
  load_balancer_type = "application"
  ip_address_type    = "ipv4"
  security_groups    = [aws_security_group.lb.id]
  subnets            = var.network.public_subnet_ids
  dynamic "access_logs" {
    for_each = var.access_logs == null ? [] : [var.access_logs]
    content {
      enabled = true
      bucket  = access_logs.value.bucket
      prefix  = access_logs.value.prefix
    }
  }
  tags = var.tags
}
resource "aws_lb_target_group" "portal" {
  for_each    = local.colors
  name        = lookup(var.name_overrides, "target-${each.key}", local.blue_green ? "TargetGroupApplication${title(each.key)}" : (local.fourfront ? "TargetGroup${replace(var.env_name, "-", "")}" : "TargetGroupPortal"))
  port        = var.web_worker_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.network.vpc_id
  health_check {
    interval = 60
    path     = "/health?format=json"
    protocol = "HTTP"
    timeout  = 10
    matcher  = "200"
  }
  stickiness {
    enabled         = true
    type            = "lb_cookie"
    cookie_duration = 3600
  }
  tags = var.tags
}
# This listener always FORWARDS. Its port changes with TLS, but the service dependency never
# points only to a redirect. B1: association with the target group exists before ECS starts.
resource "aws_lb_listener" "forward" {
  for_each          = local.colors
  load_balancer_arn = aws_lb.this[each.key].arn
  port              = local.tls ? 443 : 80
  protocol          = local.tls ? "HTTPS" : "HTTP"
  certificate_arn   = local.tls ? var.certificate_arn : null
  ssl_policy        = local.tls ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.portal[each.key].arn
  }
}
resource "aws_lb_listener" "redirect" {
  for_each          = local.tls ? local.colors : toset([])
  load_balancer_arn = aws_lb.this[each.key].arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      protocol    = "HTTPS"
      port        = "443"
      status_code = "HTTP_301"
    }
  }
}
resource "aws_ecs_service" "this" {
  for_each            = local.services
  name                = lookup(var.name_overrides, "service-${each.key}", "${var.env_name}-${each.key}")
  cluster             = aws_ecs_cluster.this[each.value.color].id
  task_definition     = aws_ecs_task_definition.this[each.key].arn
  desired_count       = local.counts[each.value.kind]
  scheduling_strategy = "REPLICA"
  network_configuration {
    subnets          = var.network.private_subnet_ids
    security_groups  = [aws_security_group.container.id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = each.value.kind == "portal" ? [1] : []
    content {
      container_name   = local.container_names.portal
      container_port   = var.web_worker_port
      target_group_arn = aws_lb_target_group.portal[each.value.color].arn
    }
  }
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = each.value.kind == "ingester" ? 1 : 0
    weight            = each.value.kind == "ingester" ? 1 : 0
  }
  capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    base              = each.value.kind == "portal" ? (local.fourfront || local.blue_green ? 8 : 2) : (each.value.kind == "indexer" ? 4 : 0)
    weight            = each.value.kind == "ingester" ? 0 : 1
  }
  depends_on = [aws_lb_listener.forward, aws_ecs_cluster_capacity_providers.this]
  tags       = var.tags
}
locals {
  # Preserve current alarm semantics, including the legacy standalone empty-queue double dash.
  alarm_queues = local.fourfront ? {} : merge({ for c in local.colors : "indexer-${c}" => {
    depth       = 1000
    depth_queue = "${var.env_name}${local.blue_green ? "-${c}" : ""}-secondary-indexer-queue"
    empty_queue = "${var.env_name}-${local.blue_green ? c : ""}-secondary-indexer-queue"
  } }, local.blue_green ? {} : { ingester = { depth = 2, depth_queue = "${var.env_name}-ingestion-queue", empty_queue = "${var.env_name}-ingestion-queue" } })
  alarms = { for a in flatten([for k, q in local.alarm_queues : [for mode in ["depth", "empty"] : {
    key = "${k}-${mode}", threshold = mode == "depth" ? q.depth : 0, queue = mode == "depth" ? q.depth_queue : q.empty_queue, mode = mode
  }]]) : a.key => a }
}
resource "aws_cloudwatch_metric_alarm" "queue" {
  for_each            = local.alarms
  alarm_name          = lookup(var.name_overrides, "alarm-${each.key}", "${var.env_name}-${each.key}")
  alarm_description   = each.value.mode == "depth" ? "Alarm if total queue depth exceeds ${each.value.threshold}" : "Alarm when queue depth reaches 0"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value.queue }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = each.value.mode == "depth" ? "GreaterThanThreshold" : "LessThanOrEqualToThreshold"
}
