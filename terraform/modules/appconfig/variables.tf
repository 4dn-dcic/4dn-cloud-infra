variable "env_name" {
  description = "ENCODED_ENV_NAME."
  type        = string
}

variable "deployment_paradigm" {
  description = "standalone => one GAC; blue_green => Blue+Green GACs (appconfig.py:136-146)."
  type        = string
  default     = "standalone"
  validation {
    condition     = contains(["standalone", "blue_green"], var.deployment_paradigm)
    error_message = "deployment_paradigm must be one of: standalone, blue_green."
  }
}

# --- Secret physical names (from Phase-0 discovery for import) -----------------------------
variable "gac_secret_name" {
  description = "GAC secret name (standalone). CFN Name=logical_id (appconfig.application_configuration_secret)."
  type        = string
  default     = null
}
variable "gac_secret_name_blue" {
  type    = string
  default = null
}
variable "gac_secret_name_green" {
  type    = string
  default = null
}
variable "foursight_secret_name" {
  type    = string
  default = null
}
variable "falcon_cid_secret_name" {
  type    = string
  default = null
}
variable "falcon_client_id_secret_name" {
  type    = string
  default = null
}
variable "falcon_client_secret_secret_name" {
  type    = string
  default = null
}

# --- Non-secret, config-derived GAC values (application_configuration_secrets.build_initial_values)
variable "deploying_iam_user" {
  type    = string
  default = "XXX: ENTER VALUE"
}
variable "data_set" {
  type    = string
  default = "deploy"
}
variable "rds_db_name" {
  type    = string
  default = "ebdb"
}
variable "rds_name" {
  type    = string
  default = null
}
variable "rds_port" {
  type    = string
  default = "5432"
}
variable "rds_username" {
  type    = string
  default = "postgresql"
}
variable "global_env_bucket" {
  type    = string
  default = null
}
variable "s3_bucket_org" {
  type    = string
  default = null
}
variable "s3_encrypt_key_id" {
  type    = string
  default = null
}
variable "admin_users" {
  type    = string
  default = ""
}

variable "initial_secret_overrides" {
  description = <<-EOT
    Optional {GAC key => value} merged into the INITIAL secret body at creation only. Use to seed
    real values (Auth0, S3_ENCRYPT_KEY, ES server) on a fresh account. SECURITY: any real value put
    here transits the plan file and state at creation (plan §8.3) — the state bucket must be
    hardened (Phase 0) before applying. After creation the content is never managed by Terraform
    (ignore_changes); it is maintained via setup-remaining-secrets and put-secret-value.
  EOT
  type        = map(string)
  default     = {}
  sensitive   = true
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
