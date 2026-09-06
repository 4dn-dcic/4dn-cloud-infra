output "application_urls" {
  value = { for c, lb in aws_lb.this : c => "${local.tls ? "https" : "http"}://${lb.dns_name}" }
}
output "cluster_arns" { value = { for c, cluster in aws_ecs_cluster.this : c => cluster.arn } }
output "task_definition_arns" { value = { for k, task in aws_ecs_task_definition.this : k => task.arn } }
