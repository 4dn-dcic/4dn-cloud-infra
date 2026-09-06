variable "policy_name_overrides" {
  description = "Discovered customer-managed policy names, keyed by ecs_secret_manager/ecs_es/ecs_sqs/ecs_ecr/ecs_s3/ecs_kms. Prevent replacement during adoption."
  type        = map(string)
  default     = {}
}
