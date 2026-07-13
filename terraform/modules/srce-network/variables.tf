# srce-network — DATA-SOURCE wrapper over the IT-provided SRCE VPCs (PR #97's 3-VPC architecture:
# Application, Database, Compute). This is the "export externally-provided IDs" pattern from
# srce_network.py (C4SRCENetwork/C4SRCEDBNetwork/C4SRCEComputeNetwork), born directly in Terraform
# per plan §1.3 — conceptually identical to modules/network-data. It creates NO VPC/subnet
# resources (IT owns them). See terraform/README.md "SRCE" for what is deferred (the SRCE-created
# cross-VPC security groups, and srce datastore/ecs/redis/sentieon).

variable "application_vpc_id" {
  description = "IT-provided SRCE Application VPC id (ECS portal + foursight)."
  type        = string
}
variable "application_private_subnet_ids" {
  description = "IT-provided private subnet ids in the Application VPC (config private.subnets)."
  type        = list(string)
  default     = []
}
variable "application_public_subnet_ids" {
  description = "IT-provided public subnet ids in the Application VPC (config public.subnets)."
  type        = list(string)
  default     = []
}

variable "db_vpc_id" {
  description = "IT-provided SRCE Database VPC id."
  type        = string
  default     = null
}
variable "db_subnet_ids" {
  description = "IT-provided subnet ids in the Database VPC."
  type        = list(string)
  default     = []
}

variable "compute_vpc_id" {
  description = "IT-provided SRCE Compute VPC id."
  type        = string
  default     = null
}
variable "compute_subnet_ids" {
  description = "IT-provided subnet ids in the Compute VPC."
  type        = list(string)
  default     = []
}
