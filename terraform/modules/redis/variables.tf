variable "env_name" {
  description = "ENCODED_ENV_NAME."
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet ids for the cache subnet group."
  type        = list(string)
}

variable "application_security_group_id" {
  description = "Application security-group id (redis.py:82)."
  type        = string
}

variable "engine_version" {
  type    = string
  default = "7.0"
}

variable "node_count" {
  description = "NumCacheClusters (redis.py DEFAULT_NODE_COUNT=1)."
  type        = number
  default     = 1
}

variable "node_type" {
  type    = string
  default = "cache.t4g.small"
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
