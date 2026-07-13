# IAM module — faithful port of src/parts/iam.py (C4IAM, SHARING='ecosystem').
#
# Scope: ECOSYSTEM-shared -> account shared/ root ONLY. Roles/user/instance-profile are per-account.
#
# Fidelity notes:
#  * Inline CFN Policies on each Role become discrete aws_iam_role_policy resources (import each).
#  * The federator IAM AccessKey is intentionally NOT created here — it is created imperatively by
#    setup-remaining-secrets (iam.py:72-73 comment; plan §6.9).
#  * Broad Resource:['*'] policies are ported AS-IS (like-for-like). Tightening is a separate,
#    reviewed follow-on (plan §8.1). Expect checkov to flag these — that is intended.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name

  names = {
    cgap  = { ecs = "CGAPECSRole", dev = "CGAPDevRole", profile = "CGAPECSInstanceProfile", autoscaling = "CGAPECSAutoscalingRole" }
    ff    = { ecs = "FFECSRole", dev = "FFDevRole", profile = "FFECSInstanceProfile", autoscaling = "FFECSAutoscalingRole" }
    smaht = { ecs = "SMaHTECSRole", dev = "SMaHTDevRole", profile = "SMaHTInstanceProfile", autoscaling = "SMaHTAutoscalingRole" }
  }
  n = local.names[var.app_kind]

  ecs_role_name         = lookup(var.role_name_overrides, "ecs", local.n.ecs)
  dev_role_name         = lookup(var.role_name_overrides, "dev", local.n.dev)
  autoscaling_role_name = lookup(var.role_name_overrides, "autoscaling", local.n.autoscaling)
  profile_name          = lookup(var.role_name_overrides, "instance_profile", local.n.profile)
  flowlog_role_name     = lookup(var.role_name_overrides, "flowlog", "VPCFlowLogRole")
  s3_user_name          = lookup(var.role_name_overrides, "s3_user", "${var.env_name}-s3-federator")

  # ECS image-pull scope: [env portal repo] + fixed repos (iam.ecs_ecr_policy).
  ecr_repo_names = concat([var.env_name], var.ecr_repo_names)
  ecr_repo_arns  = [for r in local.ecr_repo_names : "arn:aws:ecr:${local.region}:${local.account_id}:repository/${r}"]

  kms_resource = var.s3_encrypt_key_id == null ? ["*"] : ["arn:aws:kms:${local.region}:${local.account_id}:key/${var.s3_encrypt_key_id}"]

  s3_bucket_arn = "arn:aws:s3:::${var.env_name}-*"
  s3_object_arn = "arn:aws:s3:::${var.env_name}-*/*"
}

# ---------------- assume-role policies ----------------
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com", "ec2.amazonaws.com", "ecs-tasks.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "autoscaling_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["application-autoscaling.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "flowlog_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["vpc-flow-logs.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "dev_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = [local.account_id]
    }
  }
}

# ---------------- ECS assumed role + its 10 inline policies ----------------
resource "aws_iam_role" "ecs" {
  name               = local.ecs_role_name
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "ecs_secret_manager" {
  name = "ECSSecretManagerPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret", "secretsmanager:ListSecretVersionIds"]
      Resource = [
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:C4AppConfig*",
        "arn:aws:secretsmanager:${local.region}:${local.account_id}:secret:C4Datastore*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_management" {
  name = "ECSManagementPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "ecs:DescribeServices", "ecs:DescribeTaskDefinition", "ecs:DescribeTasks", "ecs:DescribeClusters",
        "ecs:ListTasks", "ecs:ListServices", "ecs:ListClusters", "ecs:RunTask", "ecs:StopTask",
        "ecs:UpdateService", "ecs:RegisterTaskDefinition", "ecs:DeregisterTaskDefinition",
        "ecs:CreateService", "ecs:DeleteService", "ecs:TagResource",
        "elasticloadbalancing:DescribeLoadBalancers", "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth", "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeRules", "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
      ]
      Resource = ["*"]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_es" {
  name = "ECSESAccessPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["es:ESHttpGet", "es:ESHttpPost", "es:ESHttpPut", "es:ESHttpDelete", "es:ESHttpHead", "es:ESHttpPatch"]
        Resource = ["arn:aws:es:${local.region}:${local.account_id}:domain/os-${var.env_name}*"]
      },
      {
        Effect   = "Allow"
        Action   = ["es:DescribeElasticsearchDomains", "es:DescribeDomain", "es:ListDomainNames"]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "ecs_sqs" {
  name = "ECSSQSAccessPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage", "sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ChangeMessageVisibility"]
        Resource = ["arn:aws:sqs:${local.region}:${local.account_id}:${var.env_name}-*"]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:ListQueues"]
        Resource = ["*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "ecs_logging" {
  name = "ECSLoggingPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
      Resource = [
        "arn:aws:logs:${local.region}:${local.account_id}:log-group:c4-*",
        "arn:aws:logs:${local.region}:${local.account_id}:log-group:c4-*:log-stream:*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_ecr" {
  name = "ECSECRPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage", "ecr:BatchCheckLayerAvailability"]
        Resource = local.ecr_repo_arns
      },
    ]
  })
}

resource "aws_iam_role_policy" "ecs_cfn" {
  name = "ECSCfnPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["cloudformation:ListStacks"]
        Resource = ["*"]
      },
      {
        Effect   = "Allow"
        Action   = ["cloudformation:DescribeStacks"]
        Resource = ["arn:aws:cloudformation:${local.region}:${local.account_id}:stack/c4-*/*"]
      },
    ]
  })
}

resource "aws_iam_role_policy" "ecs_s3" {
  name = "ECSS3Policy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [local.s3_bucket_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]
        Resource = [local.s3_object_arn]
      },
    ]
  })
}

resource "aws_iam_role_policy" "ecs_web_service" {
  name = "ECSWebServicePolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "elasticloadbalancing:Describe*", "elasticloadbalancing:DeregisterInstancesFromLoadBalancer",
        "elasticloadbalancing:RegisterInstancesWithLoadBalancer", "ec2:Describe*",
      ]
      Resource = ["*"]
    }]
  })
}

resource "aws_iam_role_policy" "ecs_kms" {
  name = "ECSKMSPolicy"
  role = aws_iam_role.ecs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"]
      Resource = local.kms_resource
    }]
  })
}

# ---------------- instance profile ----------------
resource "aws_iam_instance_profile" "ecs" {
  name = local.profile_name
  role = aws_iam_role.ecs.name
}

# ---------------- autoscaling role ----------------
resource "aws_iam_role" "autoscaling" {
  name               = local.autoscaling_role_name
  assume_role_policy = data.aws_iam_policy_document.autoscaling_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "autoscaling" {
  name = "ECSPortalAutoscalingPolicy"
  role = aws_iam_role.autoscaling.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["ecs:DescribeServices", "ecs:UpdateService", "cloudwatch:PutMetricAlarm", "cloudwatch:DescribeAlarms", "cloudwatch:DeleteAlarms"]
      Resource = "*"
    }]
  })
}

# ---------------- VPC flow-log role ----------------
resource "aws_iam_role" "flowlog" {
  name               = local.flowlog_role_name
  assume_role_policy = data.aws_iam_policy_document.flowlog_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "flowlog" {
  name = "ECSCWLoggingAccess"
  role = aws_iam_role.flowlog.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogGroups", "logs:DescribeLogStreams"]
      Resource = "*"
    }]
  })
}

# ---------------- dev user role (10 managed policies + 4 inline) ----------------
resource "aws_iam_role" "dev" {
  name               = local.dev_role_name
  assume_role_policy = data.aws_iam_policy_document.dev_assume.json
  tags               = var.tags
}

# The 10 AWS-managed policies attached to the dev role (iam.py:621-632). Discrete attachments
# instead of the deprecated managed_policy_arns argument.
locals {
  dev_managed_policy_arns = {
    cloudwatch_ro   = "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess"
    iam_ro          = "arn:aws:iam::aws:policy/IAMReadOnlyAccess"
    rds_ro          = "arn:aws:iam::aws:policy/AmazonRDSReadOnlyAccess"
    cfn_ro          = "arn:aws:iam::aws:policy/AWSCloudFormationReadOnlyAccess"
    ecr_poweruser   = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
    sqs_full        = "arn:aws:iam::aws:policy/AmazonSQSFullAccess"
    stepfunctions   = "arn:aws:iam::aws:policy/AWSStepFunctionsFullAccess"
    lambda_full     = "arn:aws:iam::aws:policy/AWSLambda_FullAccess"
    codebuild_admin = "arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess"
    ec2_full        = "arn:aws:iam::aws:policy/AmazonEC2FullAccess"
  }
}

resource "aws_iam_role_policy_attachment" "dev_managed" {
  for_each   = local.dev_managed_policy_arns
  role       = aws_iam_role.dev.name
  policy_arn = each.value
}

resource "aws_iam_role_policy" "dev_management" {
  name   = "ECSManagementPolicy"
  role   = aws_iam_role.dev.id
  policy = aws_iam_role_policy.ecs_management.policy
}

resource "aws_iam_role_policy" "dev_es" {
  name   = "ECSESAccessPolicy"
  role   = aws_iam_role.dev.id
  policy = aws_iam_role_policy.ecs_es.policy
}

resource "aws_iam_role_policy" "dev_s3" {
  name   = "ECSS3Policy"
  role   = aws_iam_role.dev.id
  policy = aws_iam_role_policy.ecs_s3.policy
}

resource "aws_iam_role_policy" "dev_kms" {
  name   = "ECSKMSPolicy"
  role   = aws_iam_role.dev.id
  policy = aws_iam_role_policy.ecs_kms.policy
}

# ---------------- S3 federator IAM user (no AccessKey — created by setup-remaining-secrets) ----------------
resource "aws_iam_user" "s3_federator" {
  name = local.s3_user_name
  tags = var.tags
}

resource "aws_iam_user_policy" "s3_federator_s3" {
  name   = "ECSS3Policy"
  user   = aws_iam_user.s3_federator.name
  policy = aws_iam_role_policy.ecs_s3.policy
}

resource "aws_iam_user_policy" "s3_federator_sts" {
  name = "ECSSTSPolicyforS3Access"
  user = aws_iam_user.s3_federator.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "sts:GetFederationToken"
      Resource = "*"
    }]
  })
}

resource "aws_iam_user_policy" "s3_federator_kms" {
  name   = "ECSKMSPolicy"
  user   = aws_iam_user.s3_federator.name
  policy = aws_iam_role_policy.ecs_kms.policy
}
