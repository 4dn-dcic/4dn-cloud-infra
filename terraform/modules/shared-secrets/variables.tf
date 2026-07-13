variable "dockerhub_secret_name" {
  description = "Secrets Manager name for the shared DockerHub credentials (shared_secrets.py DOCKERHUB_SECRET_NAME)."
  type        = string
  default     = "dhi-registry-credentials"
}

variable "tags" {
  description = "Cost-allocation tags."
  type        = map(string)
  default     = {}
}
