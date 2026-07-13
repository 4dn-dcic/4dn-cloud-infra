# Module-level provider requirement only. The provider is configured in the root
# module (accounts/<account>/<root>) so that credentials/region are supplied per account.
terraform {
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 6.0"
    }
  }
}
