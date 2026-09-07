# Native projects; no build starts, source checkout, secret lookup or AWS discovery at synthesis.
locals {
  network    = var.srce_application_network != null ? var.srce_application_network : var.standard_network
  blue_green = var.deployment_paradigm == "blue_green"
  projects = merge({ for color in(local.blue_green ? ["blue", "green"] : ["standalone"]) : "portal-${color}" => {
    name = "${var.env_name}${local.blue_green ? "-${color}" : ""}", role = "portal", source = var.portal_repository, branch = var.portal_branch
    env  = { IMAGE_REPO_NAME = var.env_name, IMAGE_TAG = local.blue_green ? color : var.image_tag }
    } }, var.app_kind == "ff" ? {} : { pipeline = {
    name   = "${var.env_name}-pipeline-builder", role = "pipeline"
    source = var.app_kind == "smaht" ? "https://github.com/smaht-dac/main-pipelines" : "https://github.com/dbmi-bgm/cgap-pipeline-main"
    branch = var.app_kind == "smaht" ? "main" : "v1.0.0"
    env    = { IMAGE_REPO_NAME = "base", IMAGE_TAG = "v1.0.0", BUILD_PATH = "cgap-pipeline-base/dockerfiles/base" }
    } }, var.app_kind != "cgap" ? {} : { external = {
    name   = "${var.env_name}-external-pipeline-builder", role = "external"
    source = "https://github.com/dbmi-bgm/cgap-pipeline-contribution", branch = "v1.0.0"
    env    = { IMAGE_REPO_NAME = "xtea_germline", IMAGE_TAG = "v1.0.0", BUILD_PATH = "xTea-germline/dockerfiles/xtea_germline" }
    } }, { tibanna = {
    name = "${var.env_name}-tibanna-awsf-builder", role = "tibanna", source = "https://github.com/4dn-dcic/tibanna", branch = var.tibanna_version
    env  = { IMAGE_TAG = var.tibanna_version }
  } })
  roles       = toset([for p in local.projects : p.role])
  secret_arns = { for r in local.roles : r => concat([var.dockerhub_secret_arn], r == "pipeline" ? [var.falcon_secret_arns.cid, var.falcon_secret_arns.client_id, var.falcon_secret_arns.client_secret] : []) }
  secret_env = { for r in local.roles : r => merge({
    DOCKERHUB_USERNAME = "${var.dockerhub_secret_arn}:username", DOCKERHUB_TOKEN = "${var.dockerhub_secret_arn}:token"
    }, r == "pipeline" ? {
    FALCON_CID = var.falcon_secret_arns.cid, FALCON_CLIENT_ID = var.falcon_secret_arns.client_id, FALCON_CLIENT_SECRET = var.falcon_secret_arns.client_secret
  } : {}) }
  # Exact current CodeBuild ECR scope (distinct from the shared runtime IAM inventory).
  fixed_repositories = ["falcon-sensor", "tibanna-awsf", "base", "fastqc", "md5", "upstream_gatk", "upstream_sentieon", "snv_germline_gatk", "snv_germline_granite", "snv_germline_misc", "snv_germline_tools", "snv_germline_vep", "snv_somatic", "cnv_germline", "manta", "sv_germline_granite", "sv_germline_tools", "sv_germline_vep", "ascat", "somatic_sentieon"]
  common_statements = [
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterface", "ec2:DescribeDhcpOptions", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups", "ec2:DescribeVpcs"], Resource = ["*"] },
    { Effect = "Allow", Action = ["ec2:CreateNetworkInterfacePermission"], Resource = ["arn:aws:ec2:${var.region}:${var.account_id}:network-interface/*"] },
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetObject", "s3:PutObject", "s3:GetBucketLocation"], Resource = ["arn:aws:s3:::${var.env_name}-*", "arn:aws:s3:::${var.env_name}-*/*"] },
    { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/codebuild/*", "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/codebuild/*:log-stream:*"] },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = ["*"] },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:PutImage", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload"], Resource = [for r in concat([var.env_name], local.fixed_repositories) : "arn:aws:ecr:${var.region}:${var.account_id}:repository/${r}"] },
    { Effect = "Allow", Action = ["codebuild:CreateReportGroup", "codebuild:CreateReport", "codebuild:UpdateReport", "codebuild:BatchPutTestCases", "codebuild:BatchPutCodeCoverages"], Resource = ["arn:aws:codebuild:${var.region}:${var.account_id}:report-group/*"] }
  ]
}
resource "aws_iam_role" "project" {
  for_each           = local.roles
  name               = lookup(var.role_name_overrides, each.key, "${var.env_name}-codebuild-${each.key}")
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["sts:AssumeRole"], Principal = { Service = ["codebuild.amazonaws.com"] } }] })
  tags               = var.tags
}
resource "aws_iam_role_policy" "project" {
  for_each = local.roles
  name     = "CodeBuildAccess"
  role     = aws_iam_role.project[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat(local.common_statements, [{
    Effect = "Allow", Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"], Resource = local.secret_arns[each.key]
  }]) })
}
resource "aws_cloudwatch_log_group" "project" {
  for_each          = local.projects
  name              = "/aws/codebuild/${each.value.name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
  lifecycle { prevent_destroy = true }
}
resource "aws_codebuild_project" "this" {
  for_each     = local.projects
  name         = each.value.name
  description  = "Build project for ${each.value.name}"
  service_role = aws_iam_role.project[each.value.role].arn
  artifacts { type = "NO_ARTIFACTS" }
  environment {
    compute_type    = "BUILD_GENERAL1_MEDIUM"
    image           = "aws/codebuild/standard:6.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true
    dynamic "environment_variable" {
      for_each = merge({ AWS_DEFAULT_REGION = var.region, AWS_ACCOUNT_ID = var.account_id }, each.value.env)
      content {
        name  = environment_variable.key
        value = environment_variable.value
        type  = "PLAINTEXT"
      }
    }
    dynamic "environment_variable" {
      for_each = local.secret_env[each.value.role]
      content {
        name  = environment_variable.key
        value = environment_variable.value
        type  = "SECRETS_MANAGER"
      }
    }
  }
  source {
    type     = "GITHUB"
    location = each.value.source
    git_submodules_config { fetch_submodules = true }
    auth {
      type     = "OAUTH"
      resource = var.github_credential_arn
    }
  }
  source_version = each.value.branch
  logs_config {
    cloudwatch_logs {
      status     = "ENABLED"
      group_name = aws_cloudwatch_log_group.project[each.key].name
    }
  }
  vpc_config {
    vpc_id             = local.network.vpc_id
    subnets            = [local.network.private_subnet_ids[0]]
    security_group_ids = [local.network.application_security_group_id]
  }
  lifecycle {
    precondition {
      condition     = try(length(local.network.private_subnet_ids) > 0 && length(setintersection(local.network.private_subnet_ids, var.excluded_subnet_ids)) == 0, false)
      error_message = "Select a complete Application network; its private subnets must not overlap public/DB/Compute subnets."
    }
  }
  depends_on = [aws_iam_role_policy.project]
  tags       = var.tags
}
