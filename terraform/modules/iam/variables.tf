variable "env_name" {
  description = "ENCODED_ENV_NAME — scopes SQS/ES/S3 policy ARNs (iam.py env-derived prefixes)."
  type        = string
}

variable "app_kind" {
  description = "cgap | ff | smaht — drives role/profile names via ConfigManager.app_case (iam.py:40-51)."
  type        = string
  validation {
    condition     = contains(["cgap", "ff", "smaht"], var.app_kind)
    error_message = "app_kind must be one of: cgap, ff, smaht."
  }
}

variable "s3_encrypt_key_id" {
  description = <<-EOT
    Optional KMS key id for the S3-encrypt key (Settings.S3_ENCRYPT_KEY_ID). When set, the KMS
    policy is scoped to that key; when null it falls back to '*' (the bootstrap case, since IAM is
    deployed before the datastore stack that creates the key — iam.py kms_policy, SEC-7).
  EOT
  type        = string
  default     = null
}

variable "ecr_repo_names" {
  description = <<-EOT
    Fixed ECR repo names the ECS image-pull policy is scoped to (iam.ecs_ecr_policy -> [env_name] +
    ecr.ECR_REPO_NAMES). Defaults to the fixed set from ecr._ECR_FIXED_REPO_EXPORTS. The env portal
    repo (named after env_name) is added automatically.
  EOT
  type        = list(string)
  default = [
    "falcon-sensor", "tibanna-awsf", "base", "fastqc", "md5",
    "upstream_gatk", "upstream_sentieon",
    "snv_germline_gatk", "snv_germline_granite", "snv_germline_misc", "snv_germline_tools",
    "snv_germline_vep", "snv_somatic", "cnv_germline", "manta",
    "sv_germline_granite", "sv_germline_tools", "sv_germline_vep", "ascat", "somatic_sentieon",
  ]
}

variable "role_name_overrides" {
  description = "Optional {ecs|dev|autoscaling|instance_profile|s3_user|flowlog => name} from discovery."
  type        = map(string)
  default     = {}
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
