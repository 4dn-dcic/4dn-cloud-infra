# Account singleton for GitHub CodeBuild source authentication, NOT one credential per project/env.
# Import/adopt the existing credential before enabling projects. No secret data source is used.
resource "aws_codebuild_source_credential" "github" {
  auth_type   = "PERSONAL_ACCESS_TOKEN"
  server_type = "GITHUB"
  token       = var.github_token
  lifecycle {
    ignore_changes  = [token]
    prevent_destroy = true
  }
}
