# Outputs mirror C4AppConfigExports (appconfig.py:29-73). Ref(secret) is the secret ARN in CFN;
# downstream stacks (codebuild) grant GetSecretValue against these ARNs.

output "gac_secret_arns" {
  description = "Map of GAC instance (standalone|Blue|Green) => secret ARN."
  value       = { for k, s in aws_secretsmanager_secret.gac : k => s.arn }
}

output "gac_secret_names" {
  description = "Map of GAC instance => secret name."
  value       = { for k, s in aws_secretsmanager_secret.gac : k => s.name }
}

output "foursight_secret_arn" {
  value       = aws_secretsmanager_secret.foursight.arn
  description = "Foursight config secret ARN."
}

output "falcon_secret_arns" {
  description = "Map of falcon stub (cid|client_id|client_secret) => secret ARN."
  value       = { for k, s in aws_secretsmanager_secret.falcon : k => s.arn }
}
