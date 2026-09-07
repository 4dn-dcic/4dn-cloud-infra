variable "service" {
  type = string
  validation {
    condition     = contains(["sentieon", "higlass", "jupyterhub"], var.service)
    error_message = "Use sentieon, higlass or jupyterhub."
  }
}
variable "env_name" { type = string }
variable "network" {
  description = "Standard or SRCE Application network. Sentieon runs in Application, not Compute."
  type        = object({ vpc_id = string, cidr_block = string, private_subnet_ids = list(string), public_subnet_ids = list(string) })
}
variable "ami" {
  description = "HMS secure AMI or legacy default; compatibility/provenance must be verified before deployment."
  type        = string
  default     = "ami-087c17d1fe0178315"
}
variable "ssh_key" { type = string }
variable "instance_type" {
  type    = string
  default = null
}
variable "admin_cidr" {
  description = "Sentieon defaults to VPC CIDR; web services preserve their legacy SSH rule unless explicitly configured."
  type        = string
  default     = null
}
variable "compute_cidr" {
  description = "SRCE Compute -> Application license access on tcp/8990 only."
  type        = string
  default     = null
}
variable "name_overrides" {
  description = "Discovered security_group, lb, target and lb_security_group names for adoption."
  type        = map(string)
  default     = {}
}
variable "tags" {
  type    = map(string)
  default = {}
}
