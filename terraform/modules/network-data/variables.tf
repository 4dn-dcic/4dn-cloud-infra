# network-data — DATA-SOURCE wrapper over an UNMANAGED, pre-existing VPC (the 4dn/fourfront
# account's IT-legacy vpc-066421dc99161d0ea). It exposes the SAME output names as modules/network
# so env-scoped modules consume either interchangeably. It creates NO resources and Terraform can
# therefore NEVER modify or destroy this network. Mirrors datastore_slim.py:66-138 parameter
# injection and PR #97's "export externally-provided IDs" pattern. See plan §1.2, §2.4, §3 Phase 1b.
#
# Keys map to custom_directories/4dn-{dev,prod}/template.config.json:
#   fourfront.vpc        -> fourfront_vpc_id
#   fourfront.vpc.subnet_a/b -> fourfront_subnet_ids
#   fourfront.rds.sg     -> fourfront_rds_sg_id
#   fourfront.https.sg   -> fourfront_https_sg_id

variable "fourfront_vpc_id" {
  description = "Pre-existing (unmanaged) VPC id, e.g. vpc-066421dc99161d0ea."
  type        = string
}

variable "fourfront_subnet_ids" {
  description = "Pre-existing private subnet ids (fourfront.vpc.subnet_a/b)."
  type        = list(string)
}

variable "fourfront_rds_sg_id" {
  description = "Pre-existing RDS security-group id (fourfront.rds.sg)."
  type        = string
}

variable "fourfront_https_sg_id" {
  description = "Pre-existing HTTPS security-group id (fourfront.https.sg)."
  type        = string
}

variable "fourfront_application_sg_id" {
  description = <<-EOT
    Optional application security-group id. The 4dn legacy config supplies only rds/https SGs; if
    an application SG id is not provided, the application_security_group_id output falls back to the
    HTTPS SG (as datastore_slim wiring effectively does).
  EOT
  type        = string
  default     = null
}
