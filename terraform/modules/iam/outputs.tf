# Outputs mirror C4IAMExports (iam.py:17-30). Consumed by ecr/datastore/ecs-app across state.

output "ecs_assumed_role_name" {
  description = "ECS-assumed role name. Mirrors ECS_ASSUMED_IAM_ROLE."
  value       = aws_iam_role.ecs.name
}

output "ecs_assumed_role_arn" {
  value       = aws_iam_role.ecs.arn
  description = "ECS-assumed role ARN (used by ecr repo policy + KMS key policy)."
}

output "instance_profile_name" {
  description = "ECS instance profile name. Mirrors ECS_INSTANCE_PROFILE."
  value       = aws_iam_instance_profile.ecs.name
}

output "autoscaling_role_name" {
  description = "Autoscaling role name. Mirrors AUTOSCALING_IAM_ROLE."
  value       = aws_iam_role.autoscaling.name
}

output "dev_role_name" {
  description = "Dev-user role name. Mirrors DEV_IAM_ROLE."
  value       = aws_iam_role.dev.name
}

output "s3_federator_user_name" {
  description = "S3-federator IAM user name. Mirrors S3_IAM_USER."
  value       = aws_iam_user.s3_federator.name
}

output "s3_federator_user_arn" {
  value       = aws_iam_user.s3_federator.arn
  description = "S3-federator IAM user ARN (referenced by the datastore KMS key policy)."
}
