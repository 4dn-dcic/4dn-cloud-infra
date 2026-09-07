variable "account_id" {
  description = "Target AWS account id. State bucket is named 4dn-cloud-infra-tf-state-<account_id>."
  type        = string
}

variable "state_bucket_name" {
  description = "Override the derived state bucket name if needed."
  type        = string
  default     = null
}

variable "lock_table_name" {
  description = "DynamoDB lock table name (plan §4.1)."
  type        = string
  default     = "4dn-cloud-infra-tf-locks"
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
