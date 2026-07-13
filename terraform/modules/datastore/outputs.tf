# Outputs mirror C4DatastoreExports / C4DatastoreExportsMixin (exports.py:41-75). These names are
# load-bearing: §2.3's runtime boto3 consumers regex-match the CFN export names, so the datastore
# CFN stack must outlive every consumer (plan §3 Phase 4 exit criterion 2, ownership ledger).

output "rds_url" {
  description = "RDS endpoint address. Mirrors ExportRDSURL."
  value       = aws_db_instance.rds.address
}

output "rds_port" {
  description = "RDS endpoint port. Mirrors ExportRDSPort."
  value       = aws_db_instance.rds.port
}

output "rds_secret_arn" {
  value       = aws_secretsmanager_secret.rds.arn
  description = "RDS master-credential secret ARN."
}

output "es_url" {
  description = "OpenSearch endpoint (standalone). Mirrors ExportElasticSearchURL (regex-matched at runtime)."
  value       = try(aws_opensearch_domain.this["default"].endpoint, null)
}

output "es_urls" {
  description = "Map of domain key => endpoint (default | blue | green)."
  value       = { for k, d in aws_opensearch_domain.this : k => d.endpoint }
}

output "sqs_queue_urls" {
  description = "Map of queue key => URL (primary|secondary|dlq|ingestion|realtime)."
  value       = { for k, q in aws_sqs_queue.this : k => q.url }
}

output "sqs_queue_arns" {
  value       = { for k, q in aws_sqs_queue.this : k => q.arn }
  description = "Map of queue key => ARN."
}

output "bucket_names" {
  description = "Map of logical key => bucket name (all 10 buckets)."
  value       = { for k, b in aws_s3_bucket.this : k => b.bucket }
}

output "kms_key_id" {
  description = "S3-encrypt KMS key id (null when s3_bucket_encryption is false)."
  value       = try(aws_kms_key.s3[0].key_id, null)
}

output "kms_key_arn" {
  value       = try(aws_kms_key.s3[0].arn, null)
  description = "S3-encrypt KMS key ARN."
}
