variable "variant" {
  description = "standard or srce (Database network inputs), or slim (legacy es- Elasticsearch 6.8, no S3/KMS/SQS)."
  type        = string
  default     = "standard"
  validation {
    condition     = contains(["standard", "srce", "slim"], var.variant)
    error_message = "Use standard, srce or slim. SRCE is not an automatic ownership/data migration."
  }
}
variable "rds_secret_name" {
  type    = string
  default = null
}
variable "rds_parameter_group_name" {
  description = "Discovered physical name; retain when adopting an existing parameter group."
  type        = string
  default     = null
}
variable "rds_subnet_group_name" {
  type    = string
  default = null
}
