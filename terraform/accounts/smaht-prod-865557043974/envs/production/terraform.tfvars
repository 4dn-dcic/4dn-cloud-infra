# Env-root inputs for smaht-prod/production. Source: custom_directories/smaht-prod/template.config.json.
# Secrets are NEVER placed here. Values currently supplied as literals in main.tf.
#   ENCODED_ENV_NAME     = production
#   rds.instance_size    = db.t3.medium
#   rds.storage_size     = 50
#   rds.az               = us-east-1a
#   elasticsearch.*      = c5.large.elasticsearch / volume 50
#   s3.bucket.org        = kmp
#   s3.bucket.encryption = true
