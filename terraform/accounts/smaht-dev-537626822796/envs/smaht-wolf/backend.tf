terraform {
  backend "s3" {
    bucket         = "4dn-cloud-infra-tf-state-537626822796"
    key            = "envs/smaht-wolf/env.tfstate"
    region         = "us-east-1"
    dynamodb_table = "4dn-cloud-infra-tf-locks"
    encrypt        = true
  }
}
