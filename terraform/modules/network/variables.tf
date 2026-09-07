variable "cidr_block" {
  description = "VPC CIDR. Faithful to network.py CIDR_BLOCK (10.0.0.0/16)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_pair_count" {
  description = <<-EOT
    Number of public/private subnet pairs to create. Mirrors Settings.SUBNET_PAIR_COUNT
    (network.py:450, default 2). Selects the first N pairs from the fixed A..F layout in
    C4NetworkExports.SUBNET_CONFIG_INFO (network.py:25-50).
  EOT
  type        = number
  default     = 2
  validation {
    condition     = var.subnet_pair_count >= 1 && var.subnet_pair_count <= 6
    error_message = "subnet_pair_count must be between 1 and 6 (only A..F are defined)."
  }
}

variable "region" {
  description = "AWS region. Used to build VPC-endpoint service names (com.amazonaws.<region>.<svc>)."
  type        = string
  default     = "us-east-1"
}

variable "db_port_low" {
  description = "Low end of the DB security-group port range (network.py DB_PORT_LOW=5400)."
  type        = number
  default     = 5400
}

variable "db_port_high" {
  description = "High end of the DB security-group port range (network.py DB_PORT_HIGH=5499)."
  type        = number
  default     = 5499
}

variable "flow_logs_enabled" {
  description = "Enable VPC flow logs (network.py vpc_flow_log_resources, default True; SEC-9)."
  type        = bool
  default     = true
}

variable "flow_logs_retention_days" {
  description = "Retention for the VPC flow-log group (network.py NETWORK_FLOW_LOGS_RETENTION_DAYS, default 365)."
  type        = number
  default     = 365
}

variable "name_prefix" {
  description = "Prefix for resource Name tags / SG group names. Import overrides real names via *_name_overrides."
  type        = string
  default     = "c4-network-main"
}

variable "tags" {
  description = "Cost-allocation tags applied to taggable resources (mirrors C4Part.tags.cost_tag_*)."
  type        = map(string)
  default     = {}
}

# --- Import-fidelity overrides -------------------------------------------------------------
# Security-group physical names are set explicitly in CFN (GroupName=logical_id). Supply the
# discovered names here so `terraform import` matches the live groups. Keys: db, https, application.
variable "security_group_name_overrides" {
  description = "Optional {db|https|application => physical SG name} from Phase-0 discovery."
  type        = map(string)
  default     = {}
}

variable "flow_log_group_name" {
  description = <<-EOT
    Optional physical name for the VPC flow-log group. CFN auto-generates this name, so a real
    import must supply the discovered name here (mirrors the *_name_overrides pattern used for the
    other resources). When null a deterministic default derived from name_prefix is used
    (offline-validation friendly; override before importing).
  EOT
  type        = string
  default     = null
}
