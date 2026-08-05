# 4dn-cloud-infra
Infrastructure provisioning for 4dn-dcic AWS environments, using Cloudformation

## Setup

See `docs/setup.rst`.

## Updates

```
poetry update  # only if updates are needed, kept in poetry.lock
poetry install
```

## Usage

To make stack changes, see `docs/making_stack_changes.rst`. To create a new stack, see `docs/create_new_stack.rst`.
To deploy from scratch, see `docs/deploy_new_account.rst`.

Validate Legacy Configuration:
    
    make legacy

Validate Alpha Configuration:

    make alpha

To lint a template:

    cfn-lint path/to/template

To get help:

    poetry run cli -h

## Documentation

See `docs/`.

## Architecture

For an in-depth overview, see `docs/architecture.rst`.

## Human Direct AWS Access Roles

Two **optional, disabled-by-default** IAM roles let people work directly in AWS without assuming
`*DevRole` (which is trusted by the account root and carries ten full-access managed policies):

| Role | Purpose |
|---|---|
| `*DevDiagnoseRole` | Read-only inspection of the running system |
| `*PowerRemediateRole` | The reversible operational actions needed to remediate those same services |

They are built by `C4IAM` in `src/parts/iam.py` and live in the IAM stack. With none of the
`human_access.*` settings present in `template.config.json` the IAM template is byte-for-byte what
it was before, and neither role is created unless approved principal ARNs are supplied - there is
no account-root trust fallback. See `docs/source/human_access_roles.rst` for the operator detail.

### Scoping model: service-level resources, tightly constrained actions

This account holds only our own resources, so these policies **do not enumerate resource
identifiers**. Two rules apply instead:

1. **Where an action supports resource-level authorization, the resource is scoped to the
   service** - `arn:aws:ecs:<region>:<account-id>:service/*`, `arn:aws:s3:::*/*`,
   `arn:aws:secretsmanager:<region>:<account-id>:secret:*`, and so on. That means every resource of
   that type in this account and region, and nothing outside it.
2. **Where an action has no resource-level authorization at all** - `ecs:Describe*`,
   `cloudwatch:GetMetricData`, `ec2:Describe*`, `sqs:ListQueues`, `sts:GetCallerIdentity` and
   friends - AWS accepts only `"*"`. Those live in a single clearly named read-only statement per
   role (`InspectServiceStateAcrossSupportedServices`, `ReadsNeededToTargetARemediation`) and are
   constrained by an `aws:RequestedRegion` condition instead.

So the real constraint is **the action list**, which is fully enumerated - no `ecs:*`, no
`s3:*`, and never `"Action": "*"` in either role. Every action is individually listed and
justified by a supported service. Both roles also carry a permission boundary; note that a
permission boundary is a **ceiling, not a grant** - it must open with an `Allow` or the roles could
do nothing at all, and it does not widen either role.

What both roles are prevented from doing, by their own `Deny` statements and by the boundary: IAM
or Identity Center administration, CloudFormation mutation, network/perimeter changes, authoring or
running new code (`ecr:PutImage`, `ecs:RegisterTaskDefinition`, `ecs:RunTask`,
`ecs:ExecuteCommand`, `lambda:UpdateFunctionCode`), irreversible queue operations
(`sqs:PurgeQueue`, `sqs:DeleteQueue`), data-plane writes, and `sts:AssumeRole` - so neither role
can be a stepping stone to the other or to the ECS runtime role.

> ### These JSON documents are illustrative, not authoritative
>
> They are provided for group discussion. **The deployed policy is whatever `src/parts/iam.py`
> renders** - that is the single source of truth, and `tests/test_human_access_roles.py` asserts
> that the action sets below match it statement for statement.
>
> They are **not deployable as written**: `<region>` and `<account-id>` are placeholders for
> CloudFormation's `AWS::Region` and `AWS::AccountId`, and the trust policy (which needs approved
> principal ARNs from `template.config.json`) is not shown here. The three inline policies attached
> to each role are also merged into one document per role for readability.

### Illustrative policy: diagnostic role (`*DevDiagnoseRole`)

Read and inspect only. Retains resource-scoped Secrets Manager and S3 object reads so a developer
can gather evidence, and denies the data-exfiltration paths a read-only role should not have
(`sqs:ReceiveMessage`, `rds:Download*LogFile*`, `lambda:GetFunctionConfiguration`,
`ssm:GetParameter`). `kms:Decrypt` is **not** shown because it is off by default; enabling
`human_access.diagnose.allow_kms_decrypt` adds a `DecryptWithApplicationKeys` statement.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "sts:GetCallerIdentity",
        "ecs:DescribeClusters",
        "ecs:DescribeServices",
        "ecs:DescribeTasks",
        "ecs:DescribeTaskDefinition",
        "ecs:DescribeContainerInstances",
        "ecs:ListClusters",
        "ecs:ListServices",
        "ecs:ListTasks",
        "ecs:ListTaskDefinitions",
        "ecs:ListContainerInstances",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeRules",
        "application-autoscaling:DescribeScalableTargets",
        "application-autoscaling:DescribeScalingPolicies",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:GetMetricData",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:ListMetrics",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "logs:DescribeQueries",
        "rds:DescribeDBInstances",
        "rds:DescribeDBParameters",
        "rds:DescribeDBSnapshots",
        "rds:DescribeEvents",
        "es:DescribeDomain",
        "es:DescribeDomains",
        "es:ListDomainNames",
        "elasticache:DescribeCacheClusters",
        "sqs:ListQueues",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:ListStacks",
        "cloudformation:GetTemplate",
        "cloudformation:GetStackPolicy",
        "ecr:GetAuthorizationToken",
        "codebuild:ListProjects",
        "codebuild:ListBuilds",
        "states:ListStateMachines",
        "states:ListExecutions",
        "lambda:ListFunctions",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVpcs",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeAvailabilityZones",
        "servicequotas:GetServiceQuota",
        "servicequotas:ListServiceQuotas",
        "tag:GetResources",
        "secretsmanager:ListSecrets",
        "kms:ListAliases"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "*",
      "Sid": "InspectServiceStateAcrossSupportedServices"
    },
    {
      "Action": [
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:GetLogGroupFields",
        "logs:GetLogRecord",
        "logs:StartQuery",
        "logs:StopQuery",
        "logs:GetQueryResults"
      ],
      "Effect": "Allow",
      "Resource": [
        "arn:aws:logs:<region>:<account-id>:log-group:*",
        "arn:aws:logs:<region>:<account-id>:log-group:*:log-stream:*"
      ],
      "Sid": "ReadApplicationLogs"
    },
    {
      "Action": [
        "s3:ListBucket",
        "s3:GetBucketLocation",
        "s3:GetBucketVersioning",
        "s3:GetBucketPolicy",
        "s3:GetBucketPolicyStatus",
        "s3:GetEncryptionConfiguration",
        "s3:GetLifecycleConfiguration",
        "s3:GetBucketPublicAccessBlock",
        "s3:GetBucketTagging",
        "s3:GetBucketCORS"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:s3:::*",
      "Sid": "InspectBucketConfiguration"
    },
    {
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:GetObjectTagging"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:s3:::*/*",
      "Sid": "ReadObjects"
    },
    {
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:ListSecretVersionIds",
        "secretsmanager:GetResourcePolicy"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:secretsmanager:<region>:<account-id>:secret:*",
      "Sid": "ReadSecrets"
    },
    {
      "Action": [
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:sqs:<region>:<account-id>:*",
      "Sid": "InspectQueueDepth"
    },
    {
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:DescribeImages",
        "ecr:ListImages",
        "ecr:BatchGetImage",
        "ecr:GetRepositoryPolicy",
        "ecr:GetLifecyclePolicy"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:ecr:<region>:<account-id>:repository/*",
      "Sid": "InspectContainerImages"
    },
    {
      "Action": [
        "codebuild:BatchGetBuilds",
        "codebuild:BatchGetProjects"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:codebuild:<region>:<account-id>:project/*",
      "Sid": "InspectBuildsAndWorkflows"
    },
    {
      "Action": [
        "states:DescribeStateMachine",
        "states:DescribeExecution",
        "states:GetExecutionHistory"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:states:<region>:<account-id>:*",
      "Sid": "InspectWorkflowExecutions"
    },
    {
      "Action": [
        "kms:DescribeKey",
        "kms:GetKeyRotationStatus"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:kms:<region>:<account-id>:key/*",
      "Sid": "InspectKeyMetadata"
    },
    {
      "Action": [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies"
      ],
      "Effect": "Allow",
      "Resource": "arn:aws:iam::<account-id>:role/*",
      "Sid": "InspectOwnRoleDefinition"
    },
    {
      "Action": [
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:PutObjectAcl",
        "secretsmanager:PutSecretValue",
        "secretsmanager:UpdateSecret",
        "secretsmanager:DeleteSecret",
        "secretsmanager:RotateSecret",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
        "rds:DownloadDBLogFilePortion",
        "rds:DownloadCompleteDBLogFile",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "sqs:ReceiveMessage",
        "sqs:SendMessage",
        "sqs:DeleteMessage",
        "sqs:PurgeQueue",
        "sqs:ChangeMessageVisibility",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "lambda:InvokeFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "es:ESHttp*",
        "ecs:UpdateService",
        "ecs:StopTask",
        "ecs:RunTask",
        "ecs:StartTask",
        "ecs:RegisterTaskDefinition",
        "ecs:CreateService",
        "ecs:DeleteService",
        "ecs:ExecuteCommand",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:BatchDeleteImage",
        "codebuild:StartBuild",
        "codebuild:StopBuild",
        "codebuild:RetryBuild",
        "states:StartExecution",
        "states:StopExecution",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms",
        "cloudwatch:SetAlarmState",
        "logs:PutRetentionPolicy",
        "cloudformation:Detect*",
        "iam:PassRole",
        "sts:AssumeRole",
        "sts:AssumeRoleWithSAML",
        "sts:AssumeRoleWithWebIdentity",
        "sts:GetFederationToken",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:GenerateDataKeyWithoutPlaintext",
        "kms:ReEncryptFrom"
      ],
      "Effect": "Deny",
      "Resource": "*",
      "Sid": "DiagnosisIsReadOnly"
    },
    {
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Deny",
      "NotAction": [
        "iam:*",
        "sts:*",
        "cloudfront:*",
        "route53:*",
        "s3:ListAllMyBuckets",
        "support:*",
        "organizations:*",
        "health:*",
        "budgets:*",
        "ce:*"
      ],
      "Resource": "*",
      "Sid": "DenyOutsideHomeRegionExceptGlobalServices"
    }
  ]
}
```

### Illustrative policy: remediation role (`*PowerRemediateRole`)

Six operational actions, each scoped to its service and each gated on region plus a live MFA
session. Every one is reversible: restart or rescale a service, stop a stuck task, release
in-flight queue messages, start or stop a workflow execution, and trigger a CI rebuild. Its read
set is deliberately narrower than the diagnostic role's - no secrets, no S3, no KMS - which keeps
CloudTrail cleanly separable into "someone was looking" and "someone was changing".

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": [
        "sts:GetCallerIdentity",
        "ecs:DescribeClusters",
        "ecs:DescribeServices",
        "ecs:DescribeTasks",
        "ecs:DescribeTaskDefinition",
        "ecs:ListClusters",
        "ecs:ListServices",
        "ecs:ListTasks",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "cloudwatch:DescribeAlarms",
        "cloudwatch:GetMetricData",
        "logs:DescribeLogGroups",
        "logs:DescribeLogStreams",
        "sqs:ListQueues",
        "codebuild:ListProjects",
        "codebuild:ListBuilds",
        "states:ListStateMachines",
        "states:ListExecutions",
        "cloudformation:DescribeStacks",
        "cloudformation:ListStacks",
        "rds:DescribeDBInstances",
        "es:DescribeDomain",
        "es:ListDomainNames"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "*",
      "Sid": "ReadsNeededToTargetARemediation"
    },
    {
      "Action": [
        "ecs:UpdateService"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:ecs:<region>:<account-id>:service/*",
      "Sid": "RestartOrRescaleServices"
    },
    {
      "Action": [
        "ecs:StopTask"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:ecs:<region>:<account-id>:task/*",
      "Sid": "StopStuckTasks"
    },
    {
      "Action": [
        "sqs:ChangeMessageVisibility"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:sqs:<region>:<account-id>:*",
      "Sid": "ReleaseInFlightQueueMessages"
    },
    {
      "Action": [
        "states:StartExecution"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:states:<region>:<account-id>:stateMachine:*",
      "Sid": "StartWorkflowExecutions"
    },
    {
      "Action": [
        "states:StopExecution"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:states:<region>:<account-id>:execution:*",
      "Sid": "StopWorkflowExecutions"
    },
    {
      "Action": [
        "codebuild:StartBuild",
        "codebuild:StopBuild",
        "codebuild:RetryBuild"
      ],
      "Condition": {
        "Bool": {
          "aws:MultiFactorAuthPresent": "true"
        },
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Allow",
      "Resource": "arn:aws:codebuild:<region>:<account-id>:project/*",
      "Sid": "RebuildApplicationImageViaCiOnly"
    },
    {
      "Action": [
        "ecs:RegisterTaskDefinition",
        "ecs:DeregisterTaskDefinition",
        "ecs:CreateService",
        "ecs:DeleteService",
        "ecs:CreateCluster",
        "ecs:DeleteCluster",
        "ecs:RunTask",
        "ecs:StartTask",
        "ecs:ExecuteCommand",
        "ecr:PutImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:BatchDeleteImage",
        "ecr:PutImageTagMutability",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:InvokeFunction",
        "lambda:GetFunction",
        "lambda:GetFunctionConfiguration",
        "sqs:PurgeQueue",
        "sqs:DeleteQueue",
        "sqs:ReceiveMessage",
        "sqs:SendMessage",
        "sqs:DeleteMessage",
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:PutObject",
        "s3:DeleteObject",
        "secretsmanager:GetSecretValue",
        "kms:Decrypt",
        "kms:GenerateDataKey",
        "kms:GenerateDataKeyWithoutPlaintext",
        "kms:ReEncryptFrom",
        "ssm:GetParameter",
        "ssm:GetParameters",
        "ssm:GetParametersByPath",
        "rds:DownloadDBLogFilePortion",
        "rds:DownloadCompleteDBLogFile",
        "es:ESHttp*",
        "iam:PassRole",
        "sts:AssumeRole",
        "sts:AssumeRoleWithSAML",
        "sts:AssumeRoleWithWebIdentity",
        "sts:GetFederationToken"
      ],
      "Effect": "Deny",
      "Resource": "*",
      "Sid": "RemediationCannotSupplyCodeDestroyDataOrReadIt"
    },
    {
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "<region>"
        }
      },
      "Effect": "Deny",
      "NotAction": [
        "iam:*",
        "sts:*",
        "cloudfront:*",
        "route53:*",
        "s3:ListAllMyBuckets",
        "support:*",
        "organizations:*",
        "health:*",
        "budgets:*",
        "ce:*"
      ],
      "Resource": "*",
      "Sid": "DenyOutsideHomeRegionExceptGlobalServices"
    }
  ]
}
```

## Testing the Deployment

Once the ECS Service has come online, the portal should be accessible from the URL output from the ECS Stack. At this
point we are ready to start testing the portal functionality by loading a demo case. Some important caveats of the
current test setup:

* Further customization is needed to run this on new environments. Full customization out of the box is still TODO.
* Bioinformatics analysis is completely mocked out (an output VCF is uploaded immediately).
* It may take a few hours for this process to run, especially if it is the first time.


Instructions for testing:  (TODO: May need some updating)

    # First load required knowledge base data
    make load-knowledge-base

    # Then perform metadata bundle submission
    make submission

    # Then, after following the "make submission" output instructions
    # queue output VCF ingestion
    make ingestion

## Deploying Foursight for Development

`foursight_development` contains scripts for running foursight checks and actions for
development purposes as well as a separate app configuration (`development_app.py`) than
the one used for deployment.

For more information, see `docs/running_foursight_from_ec2.rst`.
