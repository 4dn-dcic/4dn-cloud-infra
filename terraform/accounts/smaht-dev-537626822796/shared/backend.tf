# Per-account S3 backend (plan §4.1). One bucket + lock table per AWS account.
# `terraform init -backend=false` (used by CI/local validate) ignores this block.
terraform {
  backend "s3" {
    bucket         = "4dn-cloud-infra-tf-state-537626822796"
    key            = "shared/shared.tfstate"
    region         = "us-east-1"
    dynamodb_table = "4dn-cloud-infra-tf-locks"
    encrypt        = true
  }
}
