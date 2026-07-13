# Outputs mirror C4LoggingExports (logging.py:9-17). In CFN the export value is Ref(log_group)
# = the log-group name; downstream ecs-app consumes ApplicationLogGroup for its awslogs driver.

output "application_log_group" {
  description = "Docker/application log-group name (standalone). Mirrors ExportApplicationLogGroup."
  value       = try(aws_cloudwatch_log_group.this["docker"].name, null)
}

output "application_log_group_blue" {
  description = "Blue Docker log-group name. Mirrors ExportApplicationLogGroupBlue."
  value       = try(aws_cloudwatch_log_group.this["docker_blue"].name, null)
}

output "application_log_group_green" {
  description = "Green Docker log-group name. Mirrors ExportApplicationLogGroupGreen."
  value       = try(aws_cloudwatch_log_group.this["docker_green"].name, null)
}

output "log_group_names" {
  description = "Map of logical key => log-group name for every group this module manages."
  value       = { for k, g in aws_cloudwatch_log_group.this : k => g.name }
}

output "log_group_arns" {
  description = "Map of logical key => log-group ARN."
  value       = { for k, g in aws_cloudwatch_log_group.this : k => g.arn }
}
