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
    error_message = "Use standalone or blue_green."
  }
}
variable "account_id" { type = string }
variable "region" {
  type    = string
  default = "us-east-1"
}
variable "standard_network" {
  type    = object({ vpc_id = string, private_subnet_ids = list(string), application_security_group_id = string })
  default = null
}
variable "srce_application_network" {
  description = "vpc.id selects this Application network even if a standard network also exists; never DB/Compute."
  type        = object({ vpc_id = string, private_subnet_ids = list(string), application_security_group_id = string })
  default     = null
}
variable "excluded_subnet_ids" {
  description = "SRCE public, Database and Compute subnets; fail closed on cross-VPC overlap."
  type        = set(string)
  default     = []
}
variable "dockerhub_secret_arn" { type = string }
variable "falcon_secret_arns" {
  type = object({ cid = string, client_id = string, client_secret = string })
}
variable "github_credential_arn" {
  description = "Existing account CodeBuild GitHub SourceCredential ARN; manage/adopt it once, outside per-project state. Never a PAT value."
  type        = string
}
variable "portal_repository" {
  type    = string
  default = "https://github.com/dbmi-bgm/cgap-portal"
}
variable "portal_branch" {
  type    = string
  default = "master"
}
variable "image_tag" {
  type    = string
  default = "latest"
}
variable "tibanna_version" {
  type    = string
  default = "5.5.0"
}
variable "log_retention_days" {
  type    = number
  default = 30
}
variable "role_name_overrides" {
  description = "Discovered role names keyed by portal, pipeline, external, tibanna."
  type        = map(string)
  default     = {}
}
variable "tags" {
  type    = map(string)
  default = {}
}
