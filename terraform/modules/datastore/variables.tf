variable "env_name" {
  description = "ENCODED_ENV_NAME."
  type        = string
}

variable "deployment_paradigm" {
  description = "standalone => one OpenSearch domain; blue_green => -blue and -green domains (datastore.py:190-202)."
  type        = string
  default     = "standalone"
  validation {
    condition     = contains(["standalone", "blue_green"], var.deployment_paradigm)
    error_message = "deployment_paradigm must be one of: standalone, blue_green."
  }
}

# --- network wiring (from shared network / network-data remote state) ----------------------
variable "private_subnet_ids" {
  description = "Private subnet ids for the RDS subnet group + OpenSearch VPC options."
  type        = list(string)
}
variable "db_security_group_id" {
  description = "DB security-group id (RDS VPCSecurityGroups)."
  type        = string
}
variable "https_security_group_id" {
  description = "HTTPS security-group id (OpenSearch VPC options)."
  type        = string
}

# --- IAM wiring (KMS key policy principals) ------------------------------------------------
variable "iam_s3_federator_user_arn" {
  description = "S3-federator IAM user ARN (KMS key-use principal)."
  type        = string
  default     = null
}
variable "iam_ecs_assumed_role_arn" {
  description = "ECS-assumed role ARN (KMS key-use principal)."
  type        = string
  default     = null
}
variable "deploying_iam_user_arn" {
  description = "Admin principal for the KMS key policy (Settings.DEPLOYING_IAM_USER)."
  type        = string
}

# --- RDS sizing (datastore.py rds_instance + constants defaults) ---------------------------
variable "rds_instance_class" {
  type    = string
  default = "db.t4g.medium"
}
variable "rds_allocated_storage" {
  type    = number
  default = 30
}
variable "rds_storage_type" {
  type    = string
  default = "gp3"
}
variable "rds_postgres_version" {
  type    = string
  default = "17.6"
}
variable "rds_db_name" {
  type    = string
  default = "ebdb"
}
variable "rds_name" {
  description = "RDS DBInstanceIdentifier (Settings.RDS_NAME, default rds-<env>)."
  type        = string
  default     = null
}
variable "rds_username" {
  type    = string
  default = "postgresql"
}
variable "rds_backup_retention" {
  type    = number
  default = 7
}
variable "rds_availability_zone" {
  type    = string
  default = "us-east-1a"
}

# --- OpenSearch sizing ---------------------------------------------------------------------
variable "es_data_node_count" {
  type    = number
  default = 1
}
variable "es_data_node_type" {
  type    = string
  default = "c6g.large.search"
}
variable "es_volume_size" {
  type    = number
  default = 30
}
variable "opensearch_engine_version" {
  type    = string
  default = "OpenSearch_2.3"
}

# --- encryption ----------------------------------------------------------------------------
variable "s3_bucket_encryption" {
  description = "Whether to create the S3-encrypt KMS key and KMS-encrypt buckets (datastore.py:209, default True)."
  type        = bool
  default     = true
}

# --- bucket names (defaults derived from env_name; override with discovered names for import) -
variable "bucket_name_overrides" {
  description = <<-EOT
    Optional map of {logical_key => physical bucket name}. Logical keys: blobs, files, wfout,
    system, metadata_bundles, tibanna_output, tibanna_cwl, fs_envs, fs_results, fs_app_versions.
    Defaults follow ConfigManager.resolve_bucket_name (env-application-<suffix> / env-foursight-*);
    supply discovered names for `terraform import` (real names come from discovery, not derivation).
  EOT
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
