output "state_bucket_name" {
  description = "Name of the remote-state S3 bucket (put this in every root's backend.tf)."
  value       = aws_s3_bucket.state.bucket
}

output "lock_table_name" {
  description = "DynamoDB lock table name."
  value       = aws_dynamodb_table.locks.name
}

output "state_kms_key_arn" {
  value       = aws_kms_key.state.arn
  description = "KMS key ARN encrypting the state bucket."
}
