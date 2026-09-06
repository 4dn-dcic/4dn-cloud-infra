variable "env_name" { type = string }
variable "app_kind" {
  type = string
  validation {
    condition     = contains(["cgap", "ff", "smaht"], var.app_kind)
    error_message = "app_kind must be cgap, ff or smaht."
  }
}
variable "deployment_paradigm" {
  type    = string
  default = "standalone"
  validation {
    condition     = contains(["standalone", "blue_green"], var.deployment_paradigm)
    error_message = "Use standalone or blue_green. Blue/green belongs in the ecosystem root, once."
  }
}
variable "network" {
  description = "Selected Application network only (standard or SRCE), never DB/Compute. No AWS discovery."
  type        = object({ vpc_id = string, cidr_block = string, private_subnet_ids = list(string), public_subnet_ids = list(string) })
  validation {
    condition     = length(var.network.private_subnet_ids) > 0 && length(var.network.public_subnet_ids) >= 2 && length(setintersection(var.network.private_subnet_ids, var.network.public_subnet_ids)) == 0
    error_message = "Application network requires disjoint private and public subnets (at least two public for ALB)."
  }
}
variable "identities" {
  description = "GAC names keyed by standalone, or blue and green."
  type        = map(string)
}
variable "log_groups" {
  description = "Shared logging outputs keyed by standalone, or blue and green."
  type        = map(string)
}
variable "ecs_role_arn" { type = string }
variable "portal_repository_url" { type = string }
variable "image_tag" {
  type    = string
  default = "latest"
}
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "certificate_arn" {
  description = "ecs.lb_certificate_arn; null/empty preserves HTTP forwarding, otherwise HTTPS + redirect."
  type        = string
  default     = null
}
variable "web_worker_port" {
  type    = number
  default = 8000
}
variable "access_logs" {
  description = "Pre-existing ALB-writable bucket; no bucket or delivery policy is created here."
  type        = object({ bucket = string, prefix = optional(string, "") })
  default     = null
}
variable "crowdstrike" {
  description = "Off by default. Enabled requires verified prepare-and-exit-zero image/loader and CID ARN (not credentials)."
  type = object({
    enabled        = optional(bool, false)
    entrypoint     = optional(list(string), [])
    sensor_image   = optional(string, "")
    cid_secret_arn = optional(string, "")
    backend        = optional(string, "bpf")
    mount_path     = optional(string, "/tmp/CrowdStrike")
  })
  default = {}
  validation {
    condition     = !var.crowdstrike.enabled || (length(var.crowdstrike.entrypoint) > 0 && var.crowdstrike.sensor_image != "" && var.crowdstrike.cid_secret_arn != "")
    error_message = "Enabled CrowdStrike requires loader entrypoint, sensor image and CID secret ARN; no guessed vendor entrypoint."
  }
}
variable "task_sizes" {
  description = "Optional per-task cpu/memory: portal, indexer, ingester, initial-deployment, deployment."
  type        = map(object({ cpu = string, memory = string }))
  default     = {}
}
variable "desired_counts" {
  type    = map(number)
  default = {}
}
variable "name_overrides" {
  description = "Discovered physical names keyed by cluster-<color>, task-<color>-<task>, service-<color>-<task>, target-<color>, lb-<color>. Required for no-op adoption of CFN-generated names."
  type        = map(string)
  default     = {}
}
variable "tags" {
  type    = map(string)
  default = {}
}
