output "project_names" { value = { for k, p in aws_codebuild_project.this : k => p.name } }
output "role_arns" { value = { for k, r in aws_iam_role.project : k => r.arn } }
output "network" { value = local.network }
