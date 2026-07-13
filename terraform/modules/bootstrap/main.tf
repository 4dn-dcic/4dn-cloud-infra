# bootstrap module — the per-account remote-state backend (plan §4.1) with the §9.3 hardening.
#
# Instantiated ONCE PER ACCOUNT (three times total). Deliberately NOT self-hosted in the backend
# it creates (chicken-and-egg): apply this with LOCAL state, then the other roots point their
# backend.tf at the bucket/table it creates.
#
# SAFETY GATES (plan §8.3 — must precede Phase 2, since appconfig's initial apply and codebuild's
# PAT put real secret material in state):
#   * SSE-KMS on the state bucket (dedicated CMK).
#   * Versioning enabled.
#   * TLS-only bucket policy (deny non-SecureTransport).
#   * Full public-access block.
# DynamoDB lock tables hold no sensitive data; default encryption suffices.

locals {
  bucket_name = coalesce(var.state_bucket_name, "4dn-cloud-infra-tf-state-${var.account_id}")
}

resource "aws_kms_key" "state" {
  description             = "SSE-KMS key for the Terraform state bucket (${local.bucket_name})."
  enable_key_rotation     = true
  deletion_window_in_days = 30
  tags                    = var.tags
}

resource "aws_kms_alias" "state" {
  name          = "alias/4dn-cloud-infra-tf-state-${var.account_id}"
  target_key_id = aws_kms_key.state.key_id
}

resource "aws_s3_bucket" "state" {
  bucket = local.bucket_name
  tags   = var.tags

  # State loss is unrecoverable — refuse any plan that would destroy this bucket.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "state_tls_only" {
  bucket = aws_s3_bucket.state.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.state.arn,
        "${aws_s3_bucket.state.arn}/*",
      ]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_dynamodb_table" "locks" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags = var.tags
}
