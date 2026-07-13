variable "env_name" {
  description = "ENCODED_ENV_NAME — names the portal repo (ecr.py:120-128)."
  type        = string
}

variable "app_kind" {
  description = "cgap | ff | smaht. ff/smaht skip the CGAP pipeline repos (ecr.py:131-135)."
  type        = string
  validation {
    condition     = contains(["cgap", "ff", "smaht"], var.app_kind)
    error_message = "app_kind must be one of: cgap, ff, smaht."
  }
}

variable "iam_ecs_assumed_role_name" {
  description = <<-EOT
    Name of the ECS-assumed IAM role (from the shared iam module output). Used to build the repo
    RepositoryPolicyText push/pull ACL (ecr.build_assumed_role_arn). In CFN this is imported via the
    IAMStackNameParameter + Fn::ImportValue; here it is read from the shared iam remote state.
  EOT
  type        = string
}

variable "fixed_repo_names" {
  description = "Fixed (non-env) repos from ecr._ECR_FIXED_REPO_EXPORTS, in order."
  type        = list(string)
  default = [
    "falcon-sensor", "tibanna-awsf", "base", "fastqc", "md5",
    "upstream_gatk", "upstream_sentieon",
    "snv_germline_gatk", "snv_germline_granite", "snv_germline_misc", "snv_germline_tools",
    "snv_germline_vep", "snv_somatic", "cnv_germline", "manta",
    "sv_germline_granite", "sv_germline_tools", "sv_germline_vep", "ascat", "somatic_sentieon",
  ]
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
