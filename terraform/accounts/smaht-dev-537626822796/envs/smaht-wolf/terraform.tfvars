# Env-root inputs for smaht-wolf (env-level keys from custom_directories/smaht-wolf/template.config.json).
# Generated/maintained via terraform/tools/generate_tfvars.py. Secrets are NEVER placed here.
# Values are currently supplied as literals in main.tf; this file documents the source mapping and
# is the scaffold for promoting them to variables:
#   ENCODED_ENV_NAME       = smaht-wolf
#   app.kind               = smaht
#   app.deploy             = standalone
#   s3.bucket.encryption   = true
#   s3.encrypt_key_id      = 27d040a3-ead1-4f5a-94ce-0fa6e7f84a95
#   rds.name               = rds-smaht-wolf
#   GLOBAL_ENV_BUCKET      = smaht-wolf-foursight-envs
