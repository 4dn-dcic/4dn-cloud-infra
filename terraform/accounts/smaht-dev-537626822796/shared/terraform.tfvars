# Shared-root inputs for smaht-dev (537626822796). Account-level (ecosystem-shared) values only;
# env-level values live in envs/<env>/terraform.tfvars (plan §5.3 config split). Non-secret config
# is transformed from custom_directories/smaht-wolf/template.config.json by
# terraform/tools/generate_tfvars.py. Secrets are NEVER placed here (referenced from Secrets Manager).
#
# This root currently takes its values as literals in main.tf (module blocks). This file is the
# scaffold for promoting them to variables when the roots are parameterized; today it documents the
# source-of-truth mapping:
#   subnet.pair_count      = 6      -> module.network.subnet_pair_count
#   s3.encrypt_key_id      = 27d0…  -> module.iam.s3_encrypt_key_id
#   app.kind               = smaht  -> module.{iam,logging,ecr}.app_kind
