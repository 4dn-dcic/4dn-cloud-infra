terraform {
  backend "s3" {
    bucket         = "4dn-cloud-infra-tf-state-865557043974"
    key            = "shared/shared.tfstate"
    region         = "us-east-1"
    dynamodb_table = "4dn-cloud-infra-tf-locks"
    encrypt        = true
  }
}
