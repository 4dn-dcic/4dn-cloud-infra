# appconfig module — faithful port of src/parts/appconfig.py (C4AppConfig, SHARING='env').
#
# Scope: ENV-scoped -> each envs/<env>/ root.
#
# Builds: the Global Application Config (GAC) secret (1 standalone, or Blue+Green), a single
# Foursight config secret (same key structure), and three Falcon credential stub secrets.
#
# SAFETY GATES (plan §5.3, §8.3): Terraform owns the secrets' EXISTENCE and IAM surface, never
# their live content. Every secret version carries lifecycle.ignore_changes = [secret_string].
# The GAC body is the placeholder template from build_initial_values; ENCODED_ES_SERVER and other
# orchestration-time values are 'XXX: ENTER VALUE' and are filled post-deploy by
# setup-remaining-secrets. Seeding real Auth0/S3_ENCRYPT_KEY at creation (initial_secret_overrides)
# puts that material in state — harden the state bucket first (Phase 0 entry criterion for Phase 2).

locals {
  placeholder = "XXX: ENTER VALUE"
  env_camel   = join("", [for w in split("-", var.env_name) : title(w)])

  # build_initial_values() key template (application_configuration_secrets.py:29-86), with
  # _add_placeholders applied (None -> placeholder).
  gac_defaults = {
    deploying_iam_user                = var.deploying_iam_user
    ACCOUNT_NUMBER                    = local.placeholder
    S3_AWS_ACCESS_KEY_ID              = local.placeholder
    S3_AWS_SECRET_ACCESS_KEY          = local.placeholder
    ENCODED_AUTH0_DOMAIN              = local.placeholder
    ENCODED_AUTH0_CLIENT              = local.placeholder
    ENCODED_AUTH0_SECRET              = local.placeholder
    ENCODED_AUTH0_ALLOWED_CONNECTIONS = local.placeholder
    ENV_NAME                          = var.env_name
    ENCODED_APPLICATION_BUCKET_PREFIX = "${var.env_name}-application-"
    ENCODED_BS_ENV                    = var.env_name
    ENCODED_DATA_SET                  = var.data_set
    ENCODED_ES_SERVER                 = local.placeholder
    ENCODED_REDIS_SERVER              = local.placeholder
    ENCODED_FOURSIGHT_BUCKET_PREFIX   = "${var.env_name}-foursight-"
    ENCODED_IDENTITY                  = local.placeholder
    # PR100: concrete names prevent dcicutils inserting ENV_NAME twice.
    ENCODED_FILE_UPLOAD_BUCKET      = lookup(var.bucket_names, "files", "${var.env_name}-application-files")
    ENCODED_FILE_WFOUT_BUCKET       = lookup(var.bucket_names, "wfout", "${var.env_name}-application-wfoutput")
    ENCODED_BLOB_BUCKET             = lookup(var.bucket_names, "blobs", "${var.env_name}-application-blobs")
    ENCODED_SYSTEM_BUCKET           = lookup(var.bucket_names, "system", "${var.env_name}-application-system")
    ENCODED_METADATA_BUNDLES_BUCKET = lookup(var.bucket_names, "metadata_bundles", "${var.env_name}-application-metadata-bundles")
    ENCODED_S3_BUCKET_ORG           = var.s3_bucket_org == null ? local.placeholder : var.s3_bucket_org
    ENCODED_TIBANNA_OUTPUT_BUCKET   = ""
    LANG                            = "en_US.UTF-8"
    LC_ALL                          = "en_US.UTF-8"
    RDS_HOSTNAME                    = local.placeholder
    RDS_DB_NAME                     = var.rds_db_name
    RDS_NAME                        = var.rds_name == null ? "rds-${var.env_name}" : var.rds_name
    RDS_PORT                        = var.rds_port
    RDS_USERNAME                    = var.rds_username
    RDS_PASSWORD                    = local.placeholder
    GLOBAL_ENV_BUCKET               = var.global_env_bucket == null ? "${var.env_name}-foursight-envs" : var.global_env_bucket
    S3_ENCRYPT_KEY                  = local.placeholder
    ENCODED_S3_ENCRYPT_KEY_ID       = var.s3_encrypt_key_id == null ? local.placeholder : var.s3_encrypt_key_id
    ENCODED_SENTRY_DSN              = ""
    ENCODED_URL                     = ""
    ENCODED_ADMIN_USERS             = var.admin_users
    reCaptchaKey                    = local.placeholder
    reCaptchaSecret                 = local.placeholder
    GA4_API_SECRET                  = ""
  }
  gac_json = jsonencode(merge(local.gac_defaults, var.initial_secret_overrides))

  gac_instances = var.deployment_paradigm == "blue_green" ? {
    Blue  = coalesce(var.gac_secret_name_blue, "C4AppConfig${local.env_camel}Blue")
    Green = coalesce(var.gac_secret_name_green, "C4AppConfig${local.env_camel}Green")
    } : {
    standalone = coalesce(var.gac_secret_name, "C4AppConfig${local.env_camel}")
  }
}

# --- GAC secret(s) ---
resource "aws_secretsmanager_secret" "gac" {
  for_each    = local.gac_instances
  name        = each.value
  description = "This secret defines the application configuration for the orchestrated environment."
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "gac" {
  for_each      = aws_secretsmanager_secret.gac
  secret_id     = each.value.id
  secret_string = local.gac_json
  lifecycle {
    ignore_changes = [secret_string] # SAFETY GATE — content is unmanaged by Terraform
  }
}

# --- Foursight config secret (single, same key structure) ---
resource "aws_secretsmanager_secret" "foursight" {
  name        = coalesce(var.foursight_secret_name, "C4AppConfig${local.env_camel}Foursight")
  description = "This secret defines the foursight configuration for the orchestrated environment."
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "foursight" {
  secret_id     = aws_secretsmanager_secret.foursight.id
  secret_string = local.gac_json
  lifecycle {
    ignore_changes = [secret_string]
  }
}

# --- Falcon credential stubs (plain 'PLACEHOLDER' strings, filled post-deploy) ---
locals {
  falcon_stubs = {
    cid           = coalesce(var.falcon_cid_secret_name, "C4AppConfig${local.env_camel}FalconCID")
    client_id     = coalesce(var.falcon_client_id_secret_name, "C4AppConfig${local.env_camel}FalconClientID")
    client_secret = coalesce(var.falcon_client_secret_secret_name, "C4AppConfig${local.env_camel}FalconClientSecret")
  }
}

resource "aws_secretsmanager_secret" "falcon" {
  for_each    = local.falcon_stubs
  name        = each.value
  description = "Crowdstrike Falcon credential stub (${each.key}); populated post-deploy."
  tags        = var.tags
}

resource "aws_secretsmanager_secret_version" "falcon" {
  for_each      = aws_secretsmanager_secret.falcon
  secret_id     = each.value.id
  secret_string = "PLACEHOLDER"
  lifecycle {
    ignore_changes = [secret_string]
  }
}
