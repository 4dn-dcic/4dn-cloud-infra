# Outputs mirror C4ECRExports repo-URL exports (ecr.py output_repo_url).

output "repository_urls" {
  description = "Map of repo name => repository URL (account.dkr.ecr.region.amazonaws.com/name)."
  value       = { for k, r in aws_ecr_repository.this : k => r.repository_url }
}

output "portal_repository_url" {
  description = "Env portal repo URL. Mirrors C4ECRExports.PORTAL_REPO_URL (RepoURL)."
  value       = aws_ecr_repository.this[var.env_name].repository_url
}

output "repository_arns" {
  description = "Map of repo name => ARN."
  value       = { for k, r in aws_ecr_repository.this : k => r.arn }
}
