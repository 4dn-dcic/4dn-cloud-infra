# Mirrors C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS (the secret ARN).

output "dockerhub_credentials_arn" {
  description = "ARN of the shared DockerHub credentials secret."
  value       = aws_secretsmanager_secret.dockerhub.arn
}

output "dockerhub_credentials_name" {
  description = "Name of the shared DockerHub credentials secret."
  value       = aws_secretsmanager_secret.dockerhub.name
}
