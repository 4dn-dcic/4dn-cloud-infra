# Copied from terraform/versions.tf (keep in sync). Only appconfig is wired today (aws only).
terraform {
  required_version = ">= 1.9.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 6.0"
    }
  }
}
