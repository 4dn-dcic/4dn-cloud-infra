variable "application_vpc_id" { type = string }
variable "application_cidr" { type = string }
variable "application_private_subnet_ids" { type = list(string) }
variable "application_public_subnet_ids" { type = list(string) }
variable "db_vpc_id" { type = string }
variable "db_cidr" { type = string }
variable "db_subnet_ids" { type = list(string) }
variable "compute_vpc_id" { type = string }
variable "compute_cidr" { type = string }
variable "compute_subnet_ids" { type = list(string) }
variable "security_group_name_overrides" {
  description = "Discovered group names for adoption; keys app_db/app_https/app_application/db_db/db_https/db_application/compute_application."
  type        = map(string)
  default     = {}
}
variable "tags" {
  type    = map(string)
  default = {}
}
