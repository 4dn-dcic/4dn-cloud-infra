variable "env_name" {
  description = "Legacy federator default name only; NEVER selects permissions. Override with discovered name."
  type        = string
}
variable "app_kind" {
  type = string
  validation {
    condition     = contains(["cgap", "ff", "smaht"], var.app_kind)
    error_message = "app_kind must be cgap, ff or smaht."
  }
}
variable "ecosystem_resources" {
  description = "Complete shared inventory from iam.ecosystem_resources. See docs/source/iam_inventory.rst. No env-derived defaults."
  type = object({
    buckets         = set(string)
    queues          = set(string)
    search_domains  = set(string)
    repositories    = set(string)
    runtime_secrets = set(string)
    kms_keys        = set(string)
  })
  nullable = false
  validation {
    condition = alltrue(flatten([for key, pattern in {
      buckets         = "^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$"
      queues          = "^[a-zA-Z0-9_-]{1,80}(\\.fifo)?$"
      search_domains  = "^[a-z][a-z0-9-]{2,27}$"
      repositories    = "^[a-z0-9][a-z0-9._/-]*$"
      runtime_secrets = "^[a-zA-Z0-9/_+=.@-]+$"
      kms_keys        = "^([a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}|mrk-[a-f0-9]{32})$"
    } : concat([key == "kms_keys" || length(var.ecosystem_resources[key]) > 0], [for name in var.ecosystem_resources[key] : can(regex(pattern, name))])]))
    error_message = "Supply exact physical names (no ARNs/wildcards), all six resource classes, nonempty except explicit bootstrap kms_keys."
  }
  validation {
    condition     = alltrue([for s in var.ecosystem_resources.runtime_secrets : !can(regex("FalconClient(ID|Secret)$", s))])
    error_message = "Runtime roles must not read Falcon API build credentials."
  }
}
variable "role_name_overrides" {
  description = "Discovered {ecs|dev|autoscaling|instance_profile|s3_user|flowlog => name}; preserve identities on import."
  type        = map(string)
  default     = {}
}
variable "tags" {
  type    = map(string)
  default = {}
}
