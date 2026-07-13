variable "env_name" {
  description = "Environment name (ENCODED_ENV_NAME), e.g. smaht-wolf. Used to derive default log-group identifiers."
  type        = string
}

variable "app_kind" {
  description = "Application kind: one of cgap | ff | smaht. Mirrors Settings.APP_KIND (base.py app_case)."
  type        = string
  validation {
    condition     = contains(["cgap", "ff", "smaht"], var.app_kind)
    error_message = "app_kind must be one of: cgap, ff, smaht."
  }
}

variable "deployment_paradigm" {
  description = <<-EOT
    Deployment paradigm: "standalone" or "blue_green". Mirrors APP_DEPLOYMENT / DeploymentParadigm.
    standalone => one Docker log group + one VPC-flow log group (logging.py else-branch).
    blue_green => Docker+VPC-flow log groups doubled for blue/green (logging.py:30-50).
  EOT
  type        = string
  default     = "standalone"
  validation {
    condition     = contains(["standalone", "blue_green"], var.deployment_paradigm)
    error_message = "deployment_paradigm must be one of: standalone, blue_green."
  }
}

variable "retention_in_days" {
  description = "CloudWatch log retention. Faithful to logging.py (RetentionInDays=365)."
  type        = number
  default     = 365
}

variable "log_group_name_overrides" {
  description = <<-EOT
    Optional map of {logical_key => physical log-group name}, one entry per log group this module
    creates. Supply the ACTUAL names enumerated by Phase-0 discovery (aws cloudformation
    describe-stack-resources) so `terraform import` matches the live resource. When an entry is
    absent, a deterministic default name is derived from env_name (offline-validation friendly, but
    NOT guaranteed to match an existing CFN-assigned name — override before importing).
    Logical keys: standalone => {docker, vpc_flow}; blue_green => {docker_blue, docker_green,
    vpc_flow_blue, vpc_flow_green}.
  EOT
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Cost-allocation tags applied to every log group (mirrors C4Part.tags.cost_tag_obj)."
  type        = map(string)
  default     = {}
}
