# datastore module — faithful port of src/parts/datastore.py (C4Datastore, SHARING='env').
#
# Scope: ENV-scoped -> each envs/<env>/ root. HIGHEST-STAKES module (RDS + OpenSearch + all
# production S3 buckets). Import this stack alone (plan §3 Phase 4). Any plan that would REPLACE
# the RDS instance or an OpenSearch domain is an auto-abort (plan §7.4 point-of-no-return).
#
# Safety-relevant fidelity:
#  * aws_db_instance.deletion_protection = true (datastore.py:566 DeletionProtection=True) — do not drop.
#  * storage_encrypted = true (datastore.py:564).
#  * RDS master secret value is generated once and never re-managed (ignore_changes) so import keeps
#    the live password.
#  * KMS-encrypted buckets carry the force-encryption bucket policy (datastore.force_encryption_bucket_policy).

locals {
  rds_identifier  = coalesce(var.rds_name, "rds-${var.env_name}")
  postgres_major  = split(".", var.rds_postgres_version)[0]
  env_camel       = join("", [for w in split("-", var.env_name) : title(w)])
  kms_key_enabled = var.s3_bucket_encryption

  # OpenSearch domains: standalone => one; blue_green => -blue and -green (datastore.py:190-202).
  os_domains = var.deployment_paradigm == "blue_green" ? {
    blue  = "os-${var.env_name}-blue"
    green = "os-${var.env_name}-green"
    } : {
    default = "os-${var.env_name}"
  }

  # Bucket logical keys -> default physical names (ConfigManager.resolve_bucket_name shape).
  # Real names come from Phase-0 discovery; override via bucket_name_overrides.
  app_bucket_defaults = {
    blobs            = "${var.env_name}-application-blobs"
    files            = "${var.env_name}-application-files"
    wfout            = "${var.env_name}-application-wfoutput"
    system           = "${var.env_name}-application-system"
    metadata_bundles = "${var.env_name}-application-metadata-bundles"
    tibanna_output   = "${var.env_name}-application-tibanna-output"
    tibanna_cwl      = "${var.env_name}-application-tibanna-cwls"
  }
  fs_bucket_defaults = {
    fs_envs         = "${var.env_name}-foursight-envs"
    fs_results      = "${var.env_name}-foursight-results"
    fs_app_versions = "${var.env_name}-foursight-application-versions"
  }
  all_bucket_defaults = merge(local.app_bucket_defaults, local.fs_bucket_defaults)

  lifecycle_keys = ["files", "wfout"]
  system_key     = "system"

  buckets = {
    for key, default_name in local.all_bucket_defaults : key => {
      name          = lookup(var.bucket_name_overrides, key, default_name)
      use_lifecycle = contains(local.lifecycle_keys, key)
      # KMS for every encrypted bucket except system; system gets SSE-S3 (AES256). (datastore.py:238-251)
      use_kms    = var.s3_bucket_encryption && key != local.system_key
      use_sse_s3 = key == local.system_key
    }
  }
  kms_buckets = { for k, b in local.buckets : k => b if b.use_kms }
}

# ------------------------------------------------------------------ RDS master secret
resource "random_password" "rds" {
  length  = 30
  special = false # ExcludePunctuation=True (datastore.py:465)
}

resource "aws_secretsmanager_secret" "rds" {
  name        = "C4Datastore${local.env_camel}RDSSecret"
  description = "The RDS instance master password for ${var.env_name}."
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "rds" {
  secret_id     = aws_secretsmanager_secret.rds.id
  secret_string = jsonencode({ username = var.rds_username, password = random_password.rds.result })
  lifecycle {
    ignore_changes = [secret_string] # keep the live generated value on import
  }
}

# ------------------------------------------------------------------ RDS
resource "aws_db_parameter_group" "rds" {
  name        = "c4-rds-${var.env_name}-pg${local.postgres_major}"
  family      = "postgres${local.postgres_major}"
  description = "parameters for C4 RDS instances"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_subnet_group" "rds" {
  name        = "c4-rds-${var.env_name}-subnet-group"
  description = "RDS subnet group for ${var.env_name}."
  subnet_ids  = var.private_subnet_ids
  tags        = var.tags
}

resource "aws_db_instance" "rds" {
  identifier              = local.rds_identifier
  allocated_storage       = var.rds_allocated_storage
  instance_class          = var.rds_instance_class
  engine                  = "postgres"
  engine_version          = var.rds_postgres_version
  db_name                 = var.rds_db_name
  parameter_group_name    = aws_db_parameter_group.rds.name
  db_subnet_group_name    = aws_db_subnet_group.rds.name
  storage_type            = var.rds_storage_type
  storage_encrypted       = true
  copy_tags_to_snapshot   = true
  deletion_protection     = true # SAFETY GATE — faithful to DeletionProtection=True
  backup_retention_period = var.rds_backup_retention
  availability_zone       = var.rds_availability_zone
  publicly_accessible     = false
  vpc_security_group_ids  = [var.db_security_group_id]
  username                = var.rds_username
  password                = random_password.rds.result
  tags                    = var.tags

  lifecycle {
    # Password can't be read back on import; managed via the secret. Avoid spurious replace churn.
    ignore_changes = [password]
  }
}

# ------------------------------------------------------------------ OpenSearch
resource "aws_opensearch_domain" "this" {
  for_each       = local.os_domains
  domain_name    = each.value
  engine_version = var.opensearch_engine_version

  cluster_config {
    instance_count = var.es_data_node_count
    instance_type  = var.es_data_node_type
  }

  ebs_options {
    ebs_enabled = true
    volume_size = var.es_volume_size
    volume_type = "gp3"
  }

  node_to_node_encryption {
    enabled = true
  }
  encrypt_at_rest {
    enabled = true
  }
  domain_endpoint_options {
    enforce_https = true
  }

  vpc_options {
    security_group_ids = [var.https_security_group_id]
    subnet_ids         = [var.private_subnet_ids[0]]
  }

  tags = var.tags
}

# ------------------------------------------------------------------ SQS queues
locals {
  queues = {
    primary   = { name = "${var.env_name}-indexer-queue", visibility = 600 }
    secondary = { name = "${var.env_name}-secondary-indexer-queue", visibility = 600 }
    dlq       = { name = "${var.env_name}-indexer-queue-dlq", visibility = 600 }
    ingestion = { name = "${var.env_name}-ingestion-queue", visibility = 21600 } # 360 min
    realtime  = { name = "${var.env_name}-indexer-queue-realtime", visibility = 600 }
  }
}

resource "aws_sqs_queue" "this" {
  for_each                   = local.queues
  name                       = each.value.name
  visibility_timeout_seconds = each.value.visibility
  message_retention_seconds  = 1209600 # 14 days
  delay_seconds              = 1
  receive_wait_time_seconds  = 2
  sqs_managed_sse_enabled    = true # SEC-6
  tags                       = merge(var.tags, { Name = each.value.name })
}

# ------------------------------------------------------------------ KMS S3-encrypt key
resource "aws_kms_key" "s3" {
  count                    = local.kms_key_enabled ? 1 : 0
  description              = "Key for encrypting sensitive S3 files for ${var.env_name} environment"
  key_usage                = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  tags                     = var.tags

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "Enable Admin IAM Policies"
        Effect    = "Allow"
        Principal = { AWS = [var.deploying_iam_user_arn] }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid    = "Allow use of the key"
        Effect = "Allow"
        Principal = {
          AWS = compact([var.iam_s3_federator_user_arn, var.iam_ecs_assumed_role_arn])
        }
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_kms_alias" "s3" {
  count         = local.kms_key_enabled ? 1 : 0
  name          = "alias/c4-s3-encrypt-${var.env_name}"
  target_key_id = aws_kms_key.s3[0].key_id
}

# ------------------------------------------------------------------ S3 buckets
resource "aws_s3_bucket" "this" {
  for_each = local.buckets
  bucket   = each.value.name
  tags     = merge(var.tags, { Name = each.value.name })
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = aws_s3_bucket.this
  bucket   = each.value.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each                = aws_s3_bucket.this
  bucket                  = each.value.id
  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "kms" {
  for_each = local.kms_buckets
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3[0].key_id
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "sse_s3" {
  for_each = { for k, b in local.buckets : k => b if b.use_sse_s3 }
  bucket   = aws_s3_bucket.this[each.key].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = { for k, b in local.buckets : k => b if b.use_lifecycle }
  bucket   = aws_s3_bucket.this[each.key].id

  rule {
    id     = "IA"
    status = "Enabled"
    filter {
      tag {
        key   = "Lifecycle"
        value = "IA"
      }
    }
    transition {
      storage_class = "STANDARD_IA"
      days          = 30
    }
    noncurrent_version_transition {
      storage_class   = "STANDARD_IA"
      noncurrent_days = 30
    }
  }

  rule {
    id     = "glacier"
    status = "Enabled"
    filter {
      tag {
        key   = "Lifecycle"
        value = "Glacier"
      }
    }
    transition {
      storage_class = "GLACIER"
      days          = 1
    }
    noncurrent_version_transition {
      storage_class   = "GLACIER"
      noncurrent_days = 1
    }
  }

  rule {
    id     = "glacierda"
    status = "Enabled"
    filter {
      tag {
        key   = "Lifecycle"
        value = "GlacierDA"
      }
    }
    transition {
      storage_class = "DEEP_ARCHIVE"
      days          = 1
    }
    noncurrent_version_transition {
      storage_class   = "DEEP_ARCHIVE"
      noncurrent_days = 1
    }
  }

  rule {
    id     = "expire"
    status = "Enabled"
    filter {
      tag {
        key   = "Lifecycle"
        value = "expire"
      }
    }
    expiration {
      days = 1
    }
    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }
}

# Force-encryption bucket policy for KMS-encrypted buckets (datastore.force_encryption_bucket_policy).
resource "aws_s3_bucket_policy" "force_encryption" {
  for_each = local.kms_buckets
  bucket   = aws_s3_bucket.this[each.key].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyIncorrectEncryptionHeader"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "arn:aws:s3:::${each.value.name}/*"
        Condition = { StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
      },
      {
        Sid       = "DenyUnEncryptedObjectUploads"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:PutObject"
        Resource  = "arn:aws:s3:::${each.value.name}/*"
        Condition = { Null = { "s3:x-amz-server-side-encryption" = "true" } }
      },
    ]
  })

  # Bucket must exist before its policy (datastore.py:354 DependsOn).
  depends_on = [aws_s3_bucket_public_access_block.this]
}
