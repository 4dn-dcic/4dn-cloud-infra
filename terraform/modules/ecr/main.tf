# ECR module — faithful port of src/parts/ecr.py (C4ContainerRegistry, SHARING='ecosystem').
#
# Scope: ECOSYSTEM-shared -> account shared/ root ONLY. Depends on the shared iam module (the
# repo policy grants the ECS-assumed role push/pull).

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  ecs_role_arn = "arn:aws:iam::${local.account_id}:role/${var.iam_ecs_assumed_role_name}"

  # Always keep the env portal repo. ff/smaht keep only tibanna-awsf + falcon-sensor of the fixed
  # set; cgap keeps them all (ecr.py:131-135, using the app_kind allowlist).
  ff_smaht_allowlist = ["tibanna-awsf", "falcon-sensor"]
  fixed_repos = contains(["ff", "smaht"], var.app_kind) ? [
    for r in var.fixed_repo_names : r if contains(local.ff_smaht_allowlist, r)
  ] : var.fixed_repo_names

  repo_names = toset(concat([var.env_name], local.fixed_repos))
}

resource "aws_ecr_repository" "this" {
  for_each = local.repo_names
  name     = each.value
  tags     = var.tags

  image_scanning_configuration {
    scan_on_push = true
  }
}

# RepositoryPolicyText: push ACL to the ECS-assumed role + pull ACL to the same role
# (ecr.ecr_access_policy). Both principals are the ECS-assumed role ARN (ecr.py:147-198).
resource "aws_ecr_repository_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowPushPull"
        Effect    = "Allow"
        Principal = { AWS = [local.ecs_role_arn] }
        Action = [
          "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability",
          "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
        ]
      },
      {
        Sid       = "AllowPull"
        Effect    = "Allow"
        Principal = { AWS = [local.ecs_role_arn] }
        Action = [
          "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability",
          "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
        ]
      },
    ]
  })
}
