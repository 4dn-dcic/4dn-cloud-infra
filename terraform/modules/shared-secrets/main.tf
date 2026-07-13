# shared-secrets module — faithful port of src/parts/shared_secrets.py (C4SharedSecrets,
# SHARING='ecosystem'). One account-wide DockerHub credentials secret referenced by every
# appconfig/codebuild deploy that pulls a private base image.
#
# Scope: ECOSYSTEM-shared -> account shared/ root ONLY.
#
# Safety gate: content is populated post-deploy (aws secretsmanager put-secret-value) exactly like
# the CFN 'PLACEHOLDER' body. Terraform owns existence, never live content -> ignore_changes.

resource "aws_secretsmanager_secret" "dockerhub" {
  name        = var.dockerhub_secret_name
  description = "DockerHub username and Personal Access Token (PAT) for build/runtime use."
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "dockerhub" {
  secret_id = aws_secretsmanager_secret.dockerhub.id
  secret_string = jsonencode({
    username = "PLACEHOLDER"
    token    = "PLACEHOLDER"
  })

  # SAFETY GATE — Terraform must not manage the live credential value.
  lifecycle {
    ignore_changes = [secret_string]
  }
}
