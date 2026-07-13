# Logging module — faithful port of src/parts/logging.py (C4Logging, SHARING='ecosystem').
#
# Scope: ECOSYSTEM-shared. This module MUST be instantiated only in an account's shared/ root
# (exactly once per account). See terraform/README.md and the SHARING invariant (plan §1.1).
#
# Safety gate (plan §6.2, §4.3): every log group carries DeletionPolicy=Retain in CFN
# (logging.py:70). The Terraform analogue is lifecycle.prevent_destroy = true. This reproduces
# "you cannot tear this down without removing the lifecycle block" rather than CFN's "orphan and
# keep alive" — for log groups this is at least as protective (documented in README).

locals {
  # camelize(dehyphenate(env_name)) approximation for the default Docker log-group identifier
  # (logging.py:54). Real, CFN-assigned names come from discovery via log_group_name_overrides.
  env_camel = join("", [for w in split("-", var.env_name) : title(w)])

  docker_identifier = var.app_kind == "cgap" ? "CGAPDockerLogs" : "${local.env_camel}DockerLogs"

  # Structure mirrors logging.py: which log groups exist is a function of deployment_paradigm
  # (the Python-time conditional -> Terraform data-driven inclusion; plan §6.1).
  standalone_groups = {
    docker   = local.docker_identifier
    vpc_flow = "VPCFlowLogs"
  }
  blue_green_groups = {
    docker_blue    = "${local.env_camel}DockerLogsBlue"
    docker_green   = "${local.env_camel}DockerLogsGreen"
    vpc_flow_blue  = "VPCFlowLogsBlue"
    vpc_flow_green = "VPCFlowLogsGreen"
  }

  group_defaults = var.deployment_paradigm == "blue_green" ? local.blue_green_groups : local.standalone_groups

  # Resolve each logical key to its physical name: discovery override wins, else derived default.
  log_group_names = {
    for key, default_name in local.group_defaults :
    key => lookup(var.log_group_name_overrides, key, "c4-logging-${var.env_name}-${default_name}")
  }
}

resource "aws_cloudwatch_log_group" "this" {
  for_each = local.log_group_names

  name              = each.value
  retention_in_days = var.retention_in_days
  tags              = var.tags

  # SAFETY GATE — do not remove. Faithful to logging.py:70 DeletionPolicy=Retain.
  lifecycle {
    prevent_destroy = true
  }
}
