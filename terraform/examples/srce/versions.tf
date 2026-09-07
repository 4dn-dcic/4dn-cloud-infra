terraform {
  required_version = ">= 1.7.0"
  required_providers {
    aws    = { source = "hashicorp/aws", version = ">= 5.60.0, < 6.0.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}
