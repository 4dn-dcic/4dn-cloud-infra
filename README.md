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

For Foursight Chalice package inspection and pruning controls, see
`docs/source/pruning_chalice_packages.rst`. The normal provision command is unchanged;
use `--prune-dry-run`, `--prune-report`, `--prune-variant`, or `--no-prune` only when
needed.

## Documentation

See `docs/`.

## Architecture

For an in-depth overview, see `docs/architecture.rst`.

## Human Direct AWS Access Roles

Three **optional, disabled-by-default** IAM roles let people work directly in AWS without assuming
`*DevRole` (which trusts the account root and carries ten AWS managed policies plus runtime policies):

| Role | Purpose |
|---|---|
| `*DevDiagnoseRole` | Read-only inspection of the running system |
| `*PowerRemediateRole` | Operational API access, including privileged build/workflow delegation |
| `*InfraDeployRole` | Change-set deployment, image builds/pushes, ECS releases and cleanup of this repository's `c4-*` stacks |

They are built by `C4IAM` in `src/parts/iam.py` and live in the IAM stack. With none of the
`human_access.*` settings present in `custom/config.json` the IAM template is byte-for-byte what
it was before, and no role is created unless approved principal ARNs are supplied - there is
no account-root trust fallback. Each role has its own enable flag and principal list; enabling one
never grants another. See `docs/source/human_access_roles.rst` for the operator detail. The two
sections below describe the diagnosis/remediation roles; the deployment role has
[its own section](#deployment-role-infradeployrole).

### Scoping model: service-level resources, tightly constrained actions

These policies **do not enumerate resource identifiers**. Account/region service-level ARNs
scope resource reads and operational actions. S3 additionally requires `s3:ResourceAccount`
and explicitly denies other owners because S3 ARNs contain no account field. Remaining
wildcard discovery/inspection groups use `aws:RequestedRegion` and check `aws:ResourceAccount`
when AWS supplies it; not every inventory request carries resource ownership. See the operator
documentation for the exact scope and limits rather than inferring them from a statement name.

So the real constraint is **the action list**, which is fully enumerated - no `ecs:*`, no
`s3:*`, and never `"Action": "*"` in either role. Every action is individually listed and
justified by a supported service. Both roles also carry a permission boundary; note that a
permission boundary is a **ceiling, not a grant** - it must open with an `Allow` or the roles could
do nothing at all, and it does not widen either role.

Direct identity administration, PassRole/AssumeRole, CloudFormation/perimeter mutations,
code-authoring APIs and queue purge/deletion are denied. **These are not sandbox roles.**
Diagnosis can expose credentials in objects, secrets, logs and configuration. Remediation keeps
`StartBuild`/`RetryBuild`: buildspec/source/image overrides can execute arbitrary commands under
existing service roles, unaffected by the human boundary. Workflow inputs and ECS service
updates also permit delegated effects; operations are not guaranteed reversible. Read and
approve the [retained risks and enablement checklist](docs/source/human_access_roles.rst).

MFA is checked on role assumption, not downstream API calls. Both roles enforce a **one-hour**
maximum, IAM's minimum supported ceiling. Request 1800 seconds for remediation as guidance only,
not enforced 30-minute access. KMS decrypt remains separately off by default; enabling it may
grant access immediately through an existing key policy's delegation to account IAM.

> ### These JSON documents are illustrative, not authoritative
>
> They are provided for group discussion. **The deployed policy is whatever `src/parts/iam.py`
> renders** - that is the single source of truth, and `tests/test_human_access_roles.py` asserts
> that the actions, resources and conditions below match it statement for statement.
>
> They are **not deployable as written**: `<region>` and `<account-id>` are placeholders for
> CloudFormation's `AWS::Region` and `AWS::AccountId`, and the trust policy (which needs approved
> principal ARNs from `custom/config.json`) is not shown here. The three inline policies attached
> to each role are also merged into one document per role for readability.
> (The deployment-role example further down is different: it is rendered for one account and
> Region, and its own note explains how to attach it.)

### Illustrative policy: diagnostic role (`*DevDiagnoseRole`)

Read and inspect, including sensitive Secrets Manager and S3 data. Direct SQS message,
RDS-log, Lambda-function and SSM-parameter retrieval are denied, but other allowed reads can
still expose configuration or credentials. `kms:Decrypt` is **not** shown because it is off by default; enabling
`human_access.diagnose.allow_kms_decrypt` adds a `DecryptWithApplicationKeys` statement.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InspectServiceStateAcrossSupportedServices",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "ecs:DescribeTaskDefinition",
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
        "logs:DescribeQueries",
        "logs:StopQuery",
        "rds:DescribeEvents",
        "es:ListDomainNames",
        "elasticache:DescribeCacheClusters",
        "sqs:ListQueues",
        "cloudformation:ListStacks",
        "ecr:GetAuthorizationToken",
        "codebuild:ListProjects",
        "codebuild:ListBuilds",
        "states:ListStateMachines",
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
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        },
        "StringEqualsIfExists": {
          "aws:ResourceAccount": "<account-id>"
        }
      }
    },
    {
      "Sid": "Inspectecscluster",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeClusters"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:cluster/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectecsservice",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeServices"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:service/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectecstask",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTasks"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:task/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectecscontainerinstance",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeContainerInstances"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:container-instance/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectcloudformationstack",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResources",
        "cloudformation:GetTemplate",
        "cloudformation:GetStackPolicy"
      ],
      "Resource": "arn:aws:cloudformation:<region>:<account-id>:stack/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectlogsloggroup",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:<region>:<account-id>:log-group:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectesdomain",
      "Effect": "Allow",
      "Action": [
        "es:DescribeDomain",
        "es:DescribeDomains"
      ],
      "Resource": "arn:aws:es:<region>:<account-id>:domain/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectrdsdb",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances"
      ],
      "Resource": "arn:aws:rds:<region>:<account-id>:db:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectrdspg",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBParameters"
      ],
      "Resource": "arn:aws:rds:<region>:<account-id>:pg:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectrdssnapshot",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBSnapshots"
      ],
      "Resource": "arn:aws:rds:<region>:<account-id>:snapshot:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "InspectstatesstateMachine",
      "Effect": "Allow",
      "Action": [
        "states:ListExecutions"
      ],
      "Resource": "arn:aws:states:<region>:<account-id>:stateMachine:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "ReadApplicationLogs",
      "Effect": "Allow",
      "Action": [
        "logs:FilterLogEvents",
        "logs:GetLogEvents",
        "logs:GetLogGroupFields",
        "logs:GetLogRecord",
        "logs:StartQuery",
        "logs:GetQueryResults"
      ],
      "Resource": [
        "arn:aws:logs:<region>:<account-id>:log-group:*",
        "arn:aws:logs:<region>:<account-id>:log-group:*:log-stream:*"
      ]
    },
    {
      "Sid": "InspectBucketConfiguration",
      "Effect": "Allow",
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
      "Resource": "arn:aws:s3:::*",
      "Condition": {
        "StringEquals": {
          "s3:ResourceAccount": "<account-id>"
        }
      }
    },
    {
      "Sid": "ReadObjects",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:GetObjectTagging"
      ],
      "Resource": "arn:aws:s3:::*/*",
      "Condition": {
        "StringEquals": {
          "s3:ResourceAccount": "<account-id>"
        }
      }
    },
    {
      "Sid": "ReadSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue",
        "secretsmanager:DescribeSecret",
        "secretsmanager:ListSecretVersionIds",
        "secretsmanager:GetResourcePolicy"
      ],
      "Resource": "arn:aws:secretsmanager:<region>:<account-id>:secret:*"
    },
    {
      "Sid": "InspectQueueDepth",
      "Effect": "Allow",
      "Action": [
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl"
      ],
      "Resource": "arn:aws:sqs:<region>:<account-id>:*"
    },
    {
      "Sid": "InspectContainerImages",
      "Effect": "Allow",
      "Action": [
        "ecr:DescribeRepositories",
        "ecr:DescribeImages",
        "ecr:ListImages",
        "ecr:BatchGetImage",
        "ecr:GetRepositoryPolicy",
        "ecr:GetLifecyclePolicy"
      ],
      "Resource": "arn:aws:ecr:<region>:<account-id>:repository/*"
    },
    {
      "Sid": "InspectBuildsAndWorkflows",
      "Effect": "Allow",
      "Action": [
        "codebuild:BatchGetBuilds",
        "codebuild:BatchGetProjects"
      ],
      "Resource": "arn:aws:codebuild:<region>:<account-id>:project/*"
    },
    {
      "Sid": "InspectWorkflowExecutions",
      "Effect": "Allow",
      "Action": [
        "states:DescribeStateMachine",
        "states:DescribeExecution",
        "states:GetExecutionHistory"
      ],
      "Resource": "arn:aws:states:<region>:<account-id>:*"
    },
    {
      "Sid": "InspectKeyMetadata",
      "Effect": "Allow",
      "Action": [
        "kms:DescribeKey",
        "kms:GetKeyRotationStatus"
      ],
      "Resource": "arn:aws:kms:<region>:<account-id>:key/*"
    },
    {
      "Sid": "InspectAccountRoleDefinitions",
      "Effect": "Allow",
      "Action": [
        "iam:GetRole",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies"
      ],
      "Resource": "arn:aws:iam::<account-id>:role/*"
    },
    {
      "Sid": "DiagnosisIsReadOnly",
      "Effect": "Deny",
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
      "Resource": "*"
    },
    {
      "Sid": "DenyOutsideHomeRegionExceptGlobalServices",
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
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "DenyS3OutsideThisAccount",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": [
        "arn:aws:s3:::*",
        "arn:aws:s3:::*/*"
      ],
      "Condition": {
        "StringNotEquals": {
          "s3:ResourceAccount": "<account-id>"
        }
      }
    }
  ]
}
```

### Illustrative policy: remediation role (`*PowerRemediateRole`)

Eight operational APIs in six groups, region-pinned after MFA-protected assumption: update a
service, stop a task, change visibility using an existing receipt handle, start/stop a workflow,
and start/stop/retry a build. Direct secrets, S3 and KMS reads are denied, but delegated build
commands and workflow inputs can exercise the separately privileged execution roles.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadsNeededToTargetARemediation",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
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
        "sqs:ListQueues",
        "codebuild:ListProjects",
        "codebuild:ListBuilds",
        "states:ListStateMachines",
        "cloudformation:ListStacks",
        "es:ListDomainNames"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        },
        "StringEqualsIfExists": {
          "aws:ResourceAccount": "<account-id>"
        }
      }
    },
    {
      "Sid": "Inspectecscluster",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeClusters"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:cluster/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectecsservice",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeServices"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:service/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectecstask",
      "Effect": "Allow",
      "Action": [
        "ecs:DescribeTasks"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:task/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectcloudformationstack",
      "Effect": "Allow",
      "Action": [
        "cloudformation:DescribeStacks"
      ],
      "Resource": "arn:aws:cloudformation:<region>:<account-id>:stack/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectlogsloggroup",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogStreams"
      ],
      "Resource": "arn:aws:logs:<region>:<account-id>:log-group:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectesdomain",
      "Effect": "Allow",
      "Action": [
        "es:DescribeDomain"
      ],
      "Resource": "arn:aws:es:<region>:<account-id>:domain/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "Inspectrdsdb",
      "Effect": "Allow",
      "Action": [
        "rds:DescribeDBInstances"
      ],
      "Resource": "arn:aws:rds:<region>:<account-id>:db:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "InspectstatesstateMachine",
      "Effect": "Allow",
      "Action": [
        "states:ListExecutions"
      ],
      "Resource": "arn:aws:states:<region>:<account-id>:stateMachine:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "RestartOrRescaleServices",
      "Effect": "Allow",
      "Action": [
        "ecs:UpdateService"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:service/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "StopStuckTasks",
      "Effect": "Allow",
      "Action": [
        "ecs:StopTask"
      ],
      "Resource": "arn:aws:ecs:<region>:<account-id>:task/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "ReleaseInFlightQueueMessages",
      "Effect": "Allow",
      "Action": [
        "sqs:ChangeMessageVisibility"
      ],
      "Resource": "arn:aws:sqs:<region>:<account-id>:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "StartWorkflowExecutions",
      "Effect": "Allow",
      "Action": [
        "states:StartExecution"
      ],
      "Resource": "arn:aws:states:<region>:<account-id>:stateMachine:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "StopWorkflowExecutions",
      "Effect": "Allow",
      "Action": [
        "states:StopExecution"
      ],
      "Resource": "arn:aws:states:<region>:<account-id>:execution:*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "DelegateBuildsToExistingServiceRoles",
      "Effect": "Allow",
      "Action": [
        "codebuild:StartBuild",
        "codebuild:StopBuild",
        "codebuild:RetryBuild"
      ],
      "Resource": "arn:aws:codebuild:<region>:<account-id>:project/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    },
    {
      "Sid": "DenyDirectCodeDataAndIdentityOperations",
      "Effect": "Deny",
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
      "Resource": "*"
    },
    {
      "Sid": "DenyOutsideHomeRegionExceptGlobalServices",
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
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "<region>"
        }
      }
    }
  ]
}
```

### Deployment role (`*InfraDeployRole`)

A separately opted-in role for deploying the infrastructure this repository defines: the
`c4-*` CloudFormation stacks written by `cli provision <stack>` and the Foursight package built by
`cli provision foursight*`. It is enabled only by `human_access.deploy.enabled` together with its
own `human_access.deploy.trusted_principals`; enabling or reusing the diagnose/remediate settings
never grants it. Trust is the same as the other roles: enumerated principals, MFA at assumption,
a required `sts:SourceIdentity` label and a one-hour session. It has no permission boundary; its
explicit denies are in its own inline policy.

What it can do: create, review, execute and abandon change sets for `c4-*` stacks (never with a
CloudFormation service role); create and update the resources those templates contain; manage the
IAM roles, users and instance profiles whose CloudFormation-generated names start with `c4-`;
attach only the four AWS managed policies the CodeBuild roles use; pass `c4-*` roles only to
ECS tasks, EC2, Lambda and CodeBuild (where AWS supplies `iam:PassedToService`); create the
ECS/ELB/OpenSearch/ElastiCache/RDS service-linked roles; create and maintain (but not delete or
disable) the datastore KMS key; upload packaged artifacts to `*application-versions` buckets
in this account; start, watch and stop builds of the CodeBuild image projects; push and retag
images in this account's ECR repositories (`docker push`, `add-image-tag`,
`unrelease-most-recent-image`); run the ECS release commands `deploy-ecs` and `identity-swap`
(ECS discovery and service updates, the indexer services' ECS scaling policies and alarms, and a
rewrite of only the `main.ecosystem` file - plus Fourfront's legacy `--do-legacy` files - in the
global env buckets of this account); continue, force or roll back a failed `c4-*` stack update
and delete `c4-*` stacks (again never with a service role); and deploy, update and clean up
Tibanna (`tibanna_smaht deploy_tiger` / `cleanup`): create and replace its `tibanna_tiger_*` IAM
policies, roles, user group and worker instance profile, attaching only Tibanna's own policies
and the AWS managed policies its source attaches; assign its roles only to its functions
(`run_task`, `check_task`, `start_run`, `update_ffmeta`, `update_cost`, each `_tiger_<env>`), its
state machines and its worker instance profile; create, update and delete the `tibanna_tiger_*`
state machine definitions; and create the `tibanna-master` job table.

What it cannot do: modify or pass itself, the other human-access roles, `*DevRole` or their
policies; manage access keys, login profiles, MFA, identity providers or permissions boundaries;
create groups or customer managed policies other than Tibanna's, or new policy versions; add
users to groups; touch SSO, Organizations or billing; assume other roles; invoke Lambda, run or
exec into ECS tasks, retry or batch builds, start or redrive workflows (Tibanna's included),
launch instances with Tibanna's worker profile, open SSM sessions or delete images; delete stacks
other than `c4-*`, stack sets, or administrator-set termination protection and stack policies;
delete the data-bearing resources (RDS instances, OpenSearch/Elasticsearch domains, buckets and
objects, queues, secrets, KMS keys, ECR repositories, log groups, Redis replication groups,
DynamoDB tables), whether directly, through a change set or through `DeleteStack`; write any secret value except the RDS secret's endpoint attachment, or
rewrite a secret's payload; or act outside the deployment region.

**This is not a low-privilege role.** Deploying this system means writing IAM roles with inline
policies and handing them to services that run code (Foursight's Lambda role alone carries
`cloudformation:*`, `ec2:*`, `lambda:*` and more). Anyone who can deploy can therefore obtain any
permission a `c4-*` runtime role can be given. The denies stop direct self-escalation and
data destruction; they do not make deployment low-trust. The deployer can also read the
`C4*` secrets, because CloudFormation resolves secret references and secret resources with the
caller's credentials. Tibanna is the same: running it stays with the roles its deploy creates
(the `run_task` role carries `AmazonEC2FullAccess`), and the deployer writes those roles'
policies, so deploying Tibanna is trusted in the same way.

Builds and images delegate authority too. `StartBuild` runs a project as its CodeBuild service
role (`AWSCodeBuildAdminAccess`, `AmazonS3FullAccess`, `AmazonEC2ContainerRegistryPowerUser`,
`CloudWatchFullAccess`), with the GitHub source credential, in the VPC, in privileged mode.
Per-build overrides (buildspec, source, image, environment) are not restricted, and the deployer
can also change the project, so a build can do anything that role can, including deleting S3
objects and ECR images that this role itself may not delete. Scope is every CodeBuild project and
ECR repository in this account and region (their names come from the environment name, not
`c4-`). A pushed or retagged image runs when ECS next deploys it.

`DeleteStack` removes a stack's other resources but never its data: CloudFormation deletes each
resource with this role's session, so the data-bearing types above (and the S3 federator IAM
user, whose access key this role cannot delete) fail to delete. The stack ends in `DELETE_FAILED`
and is removed by deleting it again with `--retain-resources`; the retained resources stay in the
account until an administrator removes them, and a re-create that reuses their fixed names
collides with them. CloudFormation also refuses to delete a stack whose exports another stack
imports. Deleting an application stack takes that application offline.

Encrypted datastores (the default): KMS requires both the IAM permission and a key-policy grant,
and the datastore key policy has no account-root statement. When the deploy role is configured,
the datastore template therefore adds two key-policy statements naming it, imported from the IAM
stack's `HumanDeployRoleArn` export. One covers key creation and maintenance, including the
`kms:PutKeyPolicy` that KMS's CreateKey lockout check requires. The other covers data-key use
through S3 only. Neither grants deletion, disabling or grants, and the `deploying_iam_user`
statement is unchanged. The role can therefore create a new encrypted datastore once the IAM stack
is applied.

Prerequisites an administrator completes, because the role cannot grant them to itself:

* Apply the IAM stack with `human_access.deploy.*` enabled, using administrator credentials.
* For a datastore key created **before** the role existed, apply one datastore stack update as the
  key's existing `deploying_iam_user`, to add the statements above.
* Fill application-configuration secrets (`setup-remaining-secrets`) and run the other bootstrap
  commands, and remove resources retained by a failed creation or stack deletion (see the
  operator guide).
* Optionally enable termination protection on stacks that must never be deleted (for example the
  datastore and IAM stacks); this role cannot turn it off.

The same permissions can be attached to an existing IAM Identity Center permission set instead
of this role. The ready-to-use bundle for `SMaHT-Deployment-Manager` in account 517723527581
(us-east-1) is in
[`docs/examples/smaht-deployment-manager-517723527581-us-east-1/`](docs/examples/smaht-deployment-manager-517723527581-us-east-1/README.md).

Use `cli provision <stack>` **without** `--upload-change-set` or `--validate` (both run the AWS
CLI in Docker with only `custom/aws_creds` mounted, so they never see an assumed-role session),
then create and execute the change set with `aws cloudformation deploy --no-execute-changeset`
in the shell holding the role session. The full workflow, the CloudFormation secret-payload
boundary and the remaining limits are in `docs/source/human_access_roles.rst`.

### Illustrative policy: deployment role (`*InfraDeployRole`)

Generated from `src/parts/iam.py` for account `517723527581` in `us-east-1`, and checked
statement-for-statement by `tests/test_human_deploy_role.py`. It merges the four customer managed
policies (`InfraDeployStackPolicy`, `InfraDeployComputePolicy`, `InfraDeployDataPolicy`,
`InfraDeployTibannaPolicy`) and the inline `HumanDeployGuardrailPolicy` into one document for
reading. It is **not one attachable policy**. At about 25,500 characters it is over four times
IAM's 6,144-character limit for a managed policy, and it mixes the allow documents with the
deny-only inline policy.

To use these permissions, attach the five separate documents:

* **Existing IAM Identity Center permission set `SMaHT-Deployment-Manager` in that account:** use
  the ready-to-use bundle and setup guide in
  [`docs/examples/smaht-deployment-manager-517723527581-us-east-1/`](docs/examples/smaht-deployment-manager-517723527581-us-east-1/README.md).
* **Another account or Region:** regenerate the bundle with
  `python -m src.commands.render_deploy_policy_bundle`.
* **Opt-in custom role above:** CloudFormation creates the same documents in the IAM stack, with
  that role's own trust policy, which is not shown here.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InspectStacksAndDeploymentTargets",
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "cloudformation:DescribeStacks",
        "cloudformation:DescribeStackEvents",
        "cloudformation:DescribeStackResource",
        "cloudformation:DescribeStackResources",
        "cloudformation:ListStacks",
        "cloudformation:ListStackResources",
        "cloudformation:ListExports",
        "cloudformation:ListImports",
        "cloudformation:GetTemplate",
        "cloudformation:GetTemplateSummary",
        "cloudformation:ValidateTemplate",
        "cloudformation:DescribeChangeSet",
        "cloudformation:ListChangeSets",
        "ec2:DescribeAccountAttributes",
        "ec2:DescribeAddresses",
        "ec2:DescribeAvailabilityZones",
        "ec2:DescribeImages",
        "ec2:DescribeInstanceAttribute",
        "ec2:DescribeInstanceCreditSpecifications",
        "ec2:DescribeInstances",
        "ec2:DescribeInternetGateways",
        "ec2:DescribeKeyPairs",
        "ec2:DescribeLaunchTemplates",
        "ec2:DescribeNatGateways",
        "ec2:DescribeNetworkAcls",
        "ec2:DescribeNetworkInterfaces",
        "ec2:DescribeRouteTables",
        "ec2:DescribeSecurityGroupRules",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeSubnets",
        "ec2:DescribeVolumes",
        "ec2:DescribeVpcAttribute",
        "ec2:DescribeVpcEndpoints",
        "ec2:DescribeVpcs",
        "elasticloadbalancing:DescribeListenerAttributes",
        "elasticloadbalancing:DescribeListeners",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:DescribeLoadBalancers",
        "elasticloadbalancing:DescribeTags",
        "elasticloadbalancing:DescribeTargetGroupAttributes",
        "elasticloadbalancing:DescribeTargetGroups",
        "elasticloadbalancing:DescribeTargetHealth",
        "ecs:DescribeTaskDefinition",
        "codebuild:ListProjects",
        "ecs:ListClusters",
        "ecs:ListServices",
        "ecs:ListTaskDefinitions",
        "application-autoscaling:DescribeScalableTargets",
        "application-autoscaling:DescribeScalingPolicies",
        "rds:DescribeDBEngineVersions",
        "rds:DescribeEngineDefaultParameters",
        "rds:DescribeEvents",
        "logs:DescribeLogGroups",
        "logs:DescribeResourcePolicies",
        "logs:DescribeIndexPolicies",
        "cloudwatch:DescribeAlarms"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    },
    {
      "Sid": "ActionsWithoutResourceLevelAuthorization",
      "Effect": "Allow",
      "Action": [
        "kms:CreateKey",
        "kms:TagResource",
        "secretsmanager:GetRandomPassword",
        "codebuild:ImportSourceCredentials",
        "codebuild:ListSourceCredentials",
        "codebuild:DeleteSourceCredentials",
        "ecs:RegisterTaskDefinition",
        "ecs:DeregisterTaskDefinition",
        "ecr:GetAuthorizationToken"
      ],
      "Resource": "*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    },
    {
      "Sid": "CreateChangeSetsForC4Stacks",
      "Effect": "Allow",
      "Action": [
        "cloudformation:CreateChangeSet"
      ],
      "Resource": [
        "arn:aws:cloudformation:us-east-1:517723527581:stack/c4-*/*",
        "arn:aws:cloudformation:us-east-1:aws:transform/Serverless-2016-10-31"
      ],
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        },
        "Null": {
          "cloudformation:RoleArn": "true"
        }
      }
    },
    {
      "Sid": "ExecuteOrAbandonReviewedChangeSets",
      "Effect": "Allow",
      "Action": [
        "cloudformation:ExecuteChangeSet",
        "cloudformation:DeleteChangeSet",
        "cloudformation:CancelUpdateStack"
      ],
      "Resource": "arn:aws:cloudformation:us-east-1:517723527581:stack/c4-*/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
    },
    {
      "Sid": "RecoverOrDeleteC4Stacks",
      "Effect": "Allow",
      "Action": [
        "cloudformation:ContinueUpdateRollback",
        "cloudformation:RollbackStack",
        "cloudformation:DeleteStack"
      ],
      "Resource": "arn:aws:cloudformation:us-east-1:517723527581:stack/c4-*/*",
      "Condition": {
        "StringEquals": {
          "aws:RequestedRegion": "us-east-1"
        },
        "Null": {
          "cloudformation:RoleArn": "true"
        }
      }
    },
    {
      "Sid": "ManageGeneratedRuntimeIdentities",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:DeleteRole",
        "iam:GetRole",
        "iam:UpdateRole",
        "iam:UpdateRoleDescription",
        "iam:UpdateAssumeRolePolicy",
        "iam:PutRolePolicy",
        "iam:DeleteRolePolicy",
        "iam:GetRolePolicy",
        "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies",
        "iam:TagRole",
        "iam:UntagRole",
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:GetInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile",
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:GetUser",
        "iam:PutUserPolicy",
        "iam:DeleteUserPolicy",
        "iam:GetUserPolicy",
        "iam:ListUserPolicies",
        "iam:ListAttachedUserPolicies",
        "iam:ListGroupsForUser",
        "iam:ListAccessKeys",
        "iam:GetLoginProfile",
        "iam:TagUser",
        "iam:UntagUser"
      ],
      "Resource": [
        "arn:aws:iam::517723527581:role/c4-*",
        "arn:aws:iam::517723527581:user/c4-*",
        "arn:aws:iam::517723527581:instance-profile/c4-*"
      ]
    },
    {
      "Sid": "AttachOnlyTheManagedPoliciesTheTemplatesUse",
      "Effect": "Allow",
      "Action": [
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:role/c4-*",
      "Condition": {
        "ArnEquals": {
          "iam:PolicyARN": [
            "arn:aws:iam::aws:policy/AWSCodeBuildAdminAccess",
            "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser",
            "arn:aws:iam::aws:policy/AmazonS3FullAccess",
            "arn:aws:iam::aws:policy/CloudWatchFullAccess"
          ]
        }
      }
    },
    {
      "Sid": "PassGeneratedRolesToTheServicesThatRunThem",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::517723527581:role/c4-*",
      "Condition": {
        "StringEqualsIfExists": {
          "iam:PassedToService": [
            "codebuild.amazonaws.com",
            "ec2.amazonaws.com",
            "ecs-tasks.amazonaws.com",
            "lambda.amazonaws.com"
          ]
        }
      }
    },
    {
      "Sid": "CreateRequiredServiceLinkedRoles",
      "Effect": "Allow",
      "Action": [
        "iam:CreateServiceLinkedRole"
      ],
      "Resource": "arn:aws:iam::517723527581:role/aws-service-role/*",
      "Condition": {
        "StringEquals": {
          "iam:AWSServiceName": [
            "ecs.amazonaws.com",
            "elasticache.amazonaws.com",
            "elasticloadbalancing.amazonaws.com",
            "es.amazonaws.com",
            "opensearchservice.amazonaws.com",
            "rds.amazonaws.com",
            "ecs.application-autoscaling.amazonaws.com"
          ]
        }
      }
    },
    {
      "Sid": "ManageNetworkSecurityGroupsAndInstances",
      "Effect": "Allow",
      "Action": [
        "ec2:CreateVpc",
        "ec2:DeleteVpc",
        "ec2:ModifyVpcAttribute",
        "ec2:CreateSubnet",
        "ec2:DeleteSubnet",
        "ec2:ModifySubnetAttribute",
        "ec2:CreateInternetGateway",
        "ec2:DeleteInternetGateway",
        "ec2:AttachInternetGateway",
        "ec2:DetachInternetGateway",
        "ec2:AllocateAddress",
        "ec2:ReleaseAddress",
        "ec2:AssociateAddress",
        "ec2:DisassociateAddress",
        "ec2:CreateNatGateway",
        "ec2:DeleteNatGateway",
        "ec2:CreateRouteTable",
        "ec2:DeleteRouteTable",
        "ec2:CreateRoute",
        "ec2:ReplaceRoute",
        "ec2:DeleteRoute",
        "ec2:AssociateRouteTable",
        "ec2:DisassociateRouteTable",
        "ec2:ReplaceRouteTableAssociation",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:AuthorizeSecurityGroupEgress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupEgress",
        "ec2:UpdateSecurityGroupRuleDescriptionsIngress",
        "ec2:UpdateSecurityGroupRuleDescriptionsEgress",
        "ec2:CreateVpcEndpoint",
        "ec2:ModifyVpcEndpoint",
        "ec2:DeleteVpcEndpoints",
        "ec2:CreateTags",
        "ec2:DeleteTags",
        "ec2:RunInstances",
        "ec2:StartInstances",
        "ec2:StopInstances",
        "ec2:TerminateInstances",
        "ec2:ModifyInstanceAttribute"
      ],
      "Resource": [
        "arn:aws:ec2:us-east-1:517723527581:*",
        "arn:aws:ec2:us-east-1::image/*"
      ]
    },
    {
      "Sid": "ManageLoadBalancing",
      "Effect": "Allow",
      "Action": [
        "elasticloadbalancing:CreateLoadBalancer",
        "elasticloadbalancing:DeleteLoadBalancer",
        "elasticloadbalancing:ModifyLoadBalancerAttributes",
        "elasticloadbalancing:SetSecurityGroups",
        "elasticloadbalancing:SetSubnets",
        "elasticloadbalancing:SetIpAddressType",
        "elasticloadbalancing:CreateTargetGroup",
        "elasticloadbalancing:DeleteTargetGroup",
        "elasticloadbalancing:ModifyTargetGroup",
        "elasticloadbalancing:ModifyTargetGroupAttributes",
        "elasticloadbalancing:RegisterTargets",
        "elasticloadbalancing:DeregisterTargets",
        "elasticloadbalancing:CreateListener",
        "elasticloadbalancing:DeleteListener",
        "elasticloadbalancing:ModifyListener",
        "elasticloadbalancing:ModifyListenerAttributes",
        "elasticloadbalancing:AddTags",
        "elasticloadbalancing:RemoveTags"
      ],
      "Resource": "arn:aws:elasticloadbalancing:us-east-1:517723527581:*"
    },
    {
      "Sid": "ManageContainerServices",
      "Effect": "Allow",
      "Action": [
        "ecs:CreateCluster",
        "ecs:DeleteCluster",
        "ecs:UpdateCluster",
        "ecs:UpdateClusterSettings",
        "ecs:PutClusterCapacityProviders",
        "ecs:DescribeClusters",
        "ecs:CreateService",
        "ecs:UpdateService",
        "ecs:DeleteService",
        "ecs:DescribeServices",
        "ecs:DescribeServiceDeployments",
        "ecs:ListServiceDeployments",
        "ecs:StopServiceDeployment",
        "ecs:TagResource",
        "ecs:UntagResource",
        "ecs:ListTagsForResource"
      ],
      "Resource": "arn:aws:ecs:us-east-1:517723527581:*"
    },
    {
      "Sid": "StartWatchAndStopImageBuilds",
      "Effect": "Allow",
      "Action": [
        "codebuild:StartBuild",
        "codebuild:StopBuild",
        "codebuild:BatchGetBuilds",
        "codebuild:ListBuildsForProject"
      ],
      "Resource": "arn:aws:codebuild:us-east-1:517723527581:project/*"
    },
    {
      "Sid": "PushAndRetagImages",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage",
        "ecr:BatchGetImage",
        "ecr:DescribeImages"
      ],
      "Resource": "arn:aws:ecr:us-east-1:517723527581:repository/*"
    },
    {
      "Sid": "RepointEcsServiceScalingPolicies",
      "Effect": "Allow",
      "Action": [
        "application-autoscaling:RegisterScalableTarget",
        "application-autoscaling:PutScalingPolicy",
        "application-autoscaling:DeleteScalingPolicy"
      ],
      "Resource": "arn:aws:application-autoscaling:us-east-1:517723527581:scalable-target/*",
      "Condition": {
        "StringEquals": {
          "application-autoscaling:service-namespace": "ecs",
          "application-autoscaling:scalable-dimension": "ecs:service:DesiredCount"
        }
      }
    },
    {
      "Sid": "ManageLogGroupsAndAlarms",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:PutRetentionPolicy",
        "logs:DeleteRetentionPolicy",
        "logs:GetDataProtectionPolicy",
        "logs:TagResource",
        "logs:UntagResource",
        "logs:ListTagsForResource",
        "cloudwatch:PutMetricAlarm",
        "cloudwatch:DeleteAlarms",
        "cloudwatch:TagResource",
        "cloudwatch:UntagResource",
        "cloudwatch:ListTagsForResource"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:517723527581:log-group:*",
        "arn:aws:cloudwatch:us-east-1:517723527581:alarm:*"
      ]
    },
    {
      "Sid": "ManageFoursightFunctionsAndSchedules",
      "Effect": "Allow",
      "Action": [
        "lambda:CreateFunction",
        "lambda:DeleteFunction",
        "lambda:GetFunction",
        "lambda:UpdateFunctionCode",
        "lambda:UpdateFunctionConfiguration",
        "lambda:GetFunctionCodeSigningConfig",
        "lambda:GetRuntimeManagementConfig",
        "lambda:GetFunctionRecursionConfig",
        "lambda:GetFunctionScalingConfig",
        "lambda:AddPermission",
        "lambda:RemovePermission",
        "lambda:GetPolicy",
        "lambda:TagResource",
        "lambda:UntagResource",
        "events:PutRule",
        "events:DeleteRule",
        "events:DescribeRule",
        "events:PutTargets",
        "events:RemoveTargets",
        "events:ListTargetsByRule",
        "events:TagResource",
        "events:UntagResource",
        "events:ListTagsForResource"
      ],
      "Resource": [
        "arn:aws:lambda:us-east-1:517723527581:function:*",
        "arn:aws:events:us-east-1:517723527581:rule/*"
      ]
    },
    {
      "Sid": "ReadPublishedLambdaLayers",
      "Effect": "Allow",
      "Action": [
        "lambda:GetLayerVersion"
      ],
      "Resource": "arn:aws:lambda:us-east-1:*:layer:*:*"
    },
    {
      "Sid": "ManageFoursightRestApi",
      "Effect": "Allow",
      "Action": [
        "apigateway:GET",
        "apigateway:POST",
        "apigateway:PUT",
        "apigateway:PATCH",
        "apigateway:DELETE",
        "apigateway:UpdateRestApiPolicy"
      ],
      "Resource": [
        "arn:aws:apigateway:us-east-1::/restapis",
        "arn:aws:apigateway:us-east-1::/restapis/*",
        "arn:aws:apigateway:us-east-1::/tags/*"
      ]
    },
    {
      "Sid": "ManageDatabases",
      "Effect": "Allow",
      "Action": [
        "rds:CreateDBInstance",
        "rds:ModifyDBInstance",
        "rds:RebootDBInstance",
        "rds:DescribeDBInstances",
        "rds:DescribeDBClusters",
        "rds:DescribeDBSnapshots",
        "rds:DescribeDBClusterSnapshots",
        "rds:DescribeDBInstanceAutomatedBackups",
        "rds:CreateDBParameterGroup",
        "rds:ModifyDBParameterGroup",
        "rds:ResetDBParameterGroup",
        "rds:DeleteDBParameterGroup",
        "rds:DescribeDBParameterGroups",
        "rds:DescribeDBParameters",
        "rds:CreateDBSubnetGroup",
        "rds:ModifyDBSubnetGroup",
        "rds:DeleteDBSubnetGroup",
        "rds:DescribeDBSubnetGroups",
        "rds:AddTagsToResource",
        "rds:RemoveTagsFromResource",
        "rds:ListTagsForResource"
      ],
      "Resource": "arn:aws:rds:us-east-1:517723527581:*"
    },
    {
      "Sid": "ManageSearchDomains",
      "Effect": "Allow",
      "Action": [
        "es:CreateDomain",
        "es:UpdateDomainConfig",
        "es:UpgradeDomain",
        "es:DescribeDomain",
        "es:DescribeDomainConfig",
        "es:DescribeDomainChangeProgress",
        "es:CreateElasticsearchDomain",
        "es:UpdateElasticsearchDomainConfig",
        "es:UpgradeElasticsearchDomain",
        "es:DescribeElasticsearchDomain",
        "es:DescribeElasticsearchDomainConfig",
        "es:AddTags",
        "es:RemoveTags",
        "es:ListTags"
      ],
      "Resource": "arn:aws:es:us-east-1:517723527581:domain/*"
    },
    {
      "Sid": "ManageCaches",
      "Effect": "Allow",
      "Action": [
        "elasticache:CreateReplicationGroup",
        "elasticache:ModifyReplicationGroup",
        "elasticache:DescribeReplicationGroups",
        "elasticache:IncreaseReplicaCount",
        "elasticache:DecreaseReplicaCount",
        "elasticache:CreateCacheCluster",
        "elasticache:DeleteCacheCluster",
        "elasticache:DescribeCacheClusters",
        "elasticache:CreateCacheSubnetGroup",
        "elasticache:ModifyCacheSubnetGroup",
        "elasticache:DeleteCacheSubnetGroup",
        "elasticache:DescribeCacheSubnetGroups",
        "elasticache:AddTagsToResource",
        "elasticache:RemoveTagsFromResource",
        "elasticache:ListTagsForResource"
      ],
      "Resource": "arn:aws:elasticache:us-east-1:517723527581:*"
    },
    {
      "Sid": "ManageQueues",
      "Effect": "Allow",
      "Action": [
        "sqs:CreateQueue",
        "sqs:SetQueueAttributes",
        "sqs:GetQueueAttributes",
        "sqs:GetQueueUrl",
        "sqs:TagQueue",
        "sqs:UntagQueue",
        "sqs:ListQueueTags"
      ],
      "Resource": "arn:aws:sqs:us-east-1:517723527581:*"
    },
    {
      "Sid": "ManageBucketConfiguration",
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:ListBucket",
        "s3:GetBucketAcl",
        "s3:PutBucketAcl",
        "s3:GetBucketTagging",
        "s3:PutBucketTagging",
        "s3:GetBucketVersioning",
        "s3:PutBucketVersioning",
        "s3:GetLifecycleConfiguration",
        "s3:PutLifecycleConfiguration",
        "s3:GetEncryptionConfiguration",
        "s3:PutEncryptionConfiguration",
        "s3:GetBucketPolicy",
        "s3:PutBucketPolicy",
        "s3:DeleteBucketPolicy",
        "s3:GetBucketPublicAccessBlock",
        "s3:PutBucketPublicAccessBlock",
        "s3:GetBucketOwnershipControls",
        "s3:PutBucketOwnershipControls",
        "s3:GetBucketCORS",
        "s3:GetBucketLogging",
        "s3:GetBucketNotification",
        "s3:GetBucketObjectLockConfiguration",
        "s3:GetBucketWebsite",
        "s3:GetReplicationConfiguration",
        "s3:GetAccelerateConfiguration",
        "s3:GetAnalyticsConfiguration",
        "s3:GetIntelligentTieringConfiguration",
        "s3:GetInventoryConfiguration",
        "s3:GetMetricsConfiguration",
        "s3:GetBucketAbac",
        "s3:GetBucketMetadataTableConfiguration",
        "s3:ListTagsForResource"
      ],
      "Resource": "arn:aws:s3:::*"
    },
    {
      "Sid": "ManageImageRepositories",
      "Effect": "Allow",
      "Action": [
        "ecr:CreateRepository",
        "ecr:DescribeRepositories",
        "ecr:SetRepositoryPolicy",
        "ecr:GetRepositoryPolicy",
        "ecr:DeleteRepositoryPolicy",
        "ecr:PutImageScanningConfiguration",
        "ecr:GetLifecyclePolicy",
        "ecr:TagResource",
        "ecr:UntagResource",
        "ecr:ListTagsForResource"
      ],
      "Resource": "arn:aws:ecr:us-east-1:517723527581:repository/*"
    },
    {
      "Sid": "ManageBuildProjects",
      "Effect": "Allow",
      "Action": [
        "codebuild:CreateProject",
        "codebuild:UpdateProject",
        "codebuild:DeleteProject",
        "codebuild:BatchGetProjects"
      ],
      "Resource": "arn:aws:codebuild:us-east-1:517723527581:project/*"
    },
    {
      "Sid": "MaintainDatastoreKeys",
      "Effect": "Allow",
      "Action": [
        "kms:DescribeKey",
        "kms:GetKeyPolicy",
        "kms:PutKeyPolicy",
        "kms:GetKeyRotationStatus",
        "kms:ListResourceTags",
        "kms:UntagResource",
        "kms:UpdateKeyDescription"
      ],
      "Resource": "arn:aws:kms:us-east-1:517723527581:key/*"
    },
    {
      "Sid": "UseKeysOnlyThroughS3",
      "Effect": "Allow",
      "Action": [
        "kms:GenerateDataKey",
        "kms:Decrypt"
      ],
      "Resource": "arn:aws:kms:us-east-1:517723527581:key/*",
      "Condition": {
        "StringEquals": {
          "kms:ViaService": "s3.us-east-1.amazonaws.com"
        }
      }
    },
    {
      "Sid": "CreateApplicationSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:CreateSecret",
        "secretsmanager:DescribeSecret",
        "secretsmanager:TagResource",
        "secretsmanager:UntagResource"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:517723527581:secret:C4*"
    },
    {
      "Sid": "ResolveApplicationSecrets",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:GetSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:517723527581:secret:C4*"
    },
    {
      "Sid": "AttachDatabaseEndpointToItsSecret",
      "Effect": "Allow",
      "Action": [
        "secretsmanager:PutSecretValue"
      ],
      "Resource": "arn:aws:secretsmanager:us-east-1:517723527581:secret:C4*RDSSecret*"
    },
    {
      "Sid": "ReadGlobalEnvBucketFiles",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject"
      ],
      "Resource": [
        "arn:aws:s3:::*-foursight-envs/*",
        "arn:aws:s3:::foursight-prod-envs/*",
        "arn:aws:s3:::foursight-envs/*"
      ],
      "Condition": {
        "StringEquals": {
          "s3:ResourceAccount": "517723527581"
        }
      }
    },
    {
      "Sid": "SwitchTheLiveEcosystemFile",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::*-foursight-envs/main.ecosystem",
        "arn:aws:s3:::foursight-prod-envs/main.ecosystem",
        "arn:aws:s3:::foursight-envs/main.ecosystem",
        "arn:aws:s3:::foursight-envs/data",
        "arn:aws:s3:::foursight-envs/staging",
        "arn:aws:s3:::foursight-envs/fourfront-production-blue",
        "arn:aws:s3:::foursight-envs/fourfront-production-green"
      ],
      "Condition": {
        "StringEquals": {
          "s3:ResourceAccount": "517723527581"
        }
      }
    },
    {
      "Sid": "UploadAndReadPackagedArtifacts",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:GetObjectVersion",
        "s3:AbortMultipartUpload"
      ],
      "Resource": "arn:aws:s3:::*application-versions/*",
      "Condition": {
        "StringEquals": {
          "s3:ResourceAccount": "517723527581"
        }
      }
    },
    {
      "Sid": "ManageTibannaPolicies",
      "Effect": "Allow",
      "Action": [
        "iam:CreatePolicy",
        "iam:DeletePolicy",
        "iam:DeletePolicyVersion",
        "iam:GetPolicy",
        "iam:ListPolicyVersions",
        "iam:ListEntitiesForPolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:policy/tibanna_tiger_*"
    },
    {
      "Sid": "ManageTibannaRolesAndWorkerInstanceProfile",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:GetRole",
        "iam:DeleteRole",
        "iam:ListAttachedRolePolicies",
        "iam:ListInstanceProfilesForRole",
        "iam:CreateInstanceProfile",
        "iam:DeleteInstanceProfile",
        "iam:AddRoleToInstanceProfile",
        "iam:RemoveRoleFromInstanceProfile"
      ],
      "Resource": [
        "arn:aws:iam::517723527581:role/tibanna_tiger_*",
        "arn:aws:iam::517723527581:instance-profile/tibanna_tiger_*_for_ec2"
      ]
    },
    {
      "Sid": "CreateTibannaLambdaInitRole",
      "Effect": "Allow",
      "Action": [
        "iam:CreateRole",
        "iam:GetRole"
      ],
      "Resource": "arn:aws:iam::517723527581:role/tibanna_lambda_init_role"
    },
    {
      "Sid": "AttachTibannaRolePolicies",
      "Effect": "Allow",
      "Action": [
        "iam:AttachRolePolicy",
        "iam:DetachRolePolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:role/tibanna_tiger_*",
      "Condition": {
        "ArnLike": {
          "iam:PolicyARN": [
            "arn:aws:iam::517723527581:policy/tibanna_tiger_*",
            "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
            "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
            "arn:aws:iam::aws:policy/AWSElasticBeanstalkReadOnly",
            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaRole"
          ]
        }
      }
    },
    {
      "Sid": "ManageTibannaUserGroup",
      "Effect": "Allow",
      "Action": [
        "iam:CreateGroup",
        "iam:GetGroup",
        "iam:DeleteGroup",
        "iam:ListAttachedGroupPolicies",
        "iam:RemoveUserFromGroup"
      ],
      "Resource": "arn:aws:iam::517723527581:group/tibanna_tiger_*"
    },
    {
      "Sid": "AttachTibannaGroupPolicies",
      "Effect": "Allow",
      "Action": [
        "iam:AttachGroupPolicy",
        "iam:DetachGroupPolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:group/tibanna_tiger_*",
      "Condition": {
        "ArnLike": {
          "iam:PolicyARN": [
            "arn:aws:iam::517723527581:policy/tibanna_tiger_*",
            "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
          ]
        }
      }
    },
    {
      "Sid": "AssignTibannaFunctionRoles",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::517723527581:role/tibanna_tiger_*_run_task",
        "arn:aws:iam::517723527581:role/tibanna_tiger_*_check_task",
        "arn:aws:iam::517723527581:role/tibanna_tiger_*_start_run",
        "arn:aws:iam::517723527581:role/tibanna_tiger_*_update_ffmeta",
        "arn:aws:iam::517723527581:role/tibanna_tiger_*_update_cost"
      ],
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "lambda.amazonaws.com"
        },
        "ArnLikeIfExists": {
          "iam:AssociatedResourceArn": [
            "arn:aws:lambda:us-east-1:517723527581:function:run_task_tiger_*",
            "arn:aws:lambda:us-east-1:517723527581:function:check_task_tiger_*",
            "arn:aws:lambda:us-east-1:517723527581:function:start_run_tiger_*",
            "arn:aws:lambda:us-east-1:517723527581:function:update_ffmeta_tiger_*",
            "arn:aws:lambda:us-east-1:517723527581:function:update_cost_tiger_*"
          ]
        }
      }
    },
    {
      "Sid": "AssignTibannaStateMachineRole",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::517723527581:role/tibanna_tiger_*_states",
      "Condition": {
        "StringEquals": {
          "iam:PassedToService": "states.amazonaws.com"
        },
        "ArnLikeIfExists": {
          "iam:AssociatedResourceArn": "arn:aws:states:us-east-1:517723527581:stateMachine:tibanna_tiger_*"
        }
      }
    },
    {
      "Sid": "AssignTibannaWorkerRoleToItsInstanceProfile",
      "Effect": "Allow",
      "Action": [
        "iam:PassRole"
      ],
      "Resource": "arn:aws:iam::517723527581:role/tibanna_tiger_*_for_ec2",
      "Condition": {
        "StringEqualsIfExists": {
          "iam:PassedToService": "ec2.amazonaws.com"
        }
      }
    },
    {
      "Sid": "ManageTibannaStateMachineDefinitions",
      "Effect": "Allow",
      "Action": [
        "states:CreateStateMachine",
        "states:UpdateStateMachine",
        "states:DeleteStateMachine"
      ],
      "Resource": "arn:aws:states:us-east-1:517723527581:stateMachine:tibanna_tiger_*"
    },
    {
      "Sid": "CreateTibannaJobTable",
      "Effect": "Allow",
      "Action": [
        "dynamodb:DescribeTable",
        "dynamodb:CreateTable"
      ],
      "Resource": "arn:aws:dynamodb:us-east-1:517723527581:table/tibanna-master"
    },
    {
      "Sid": "NeverModifyHumanAccessIdentities",
      "Effect": "Deny",
      "Action": [
        "iam:Create*",
        "iam:Delete*",
        "iam:Update*",
        "iam:Put*",
        "iam:Attach*",
        "iam:Detach*",
        "iam:Add*",
        "iam:Remove*",
        "iam:Tag*",
        "iam:Untag*",
        "iam:SetDefaultPolicyVersion",
        "iam:PassRole"
      ],
      "Resource": [
        "arn:aws:iam::517723527581:role/*DevDiagnoseRole*",
        "arn:aws:iam::517723527581:role/*PowerRemediateRole*",
        "arn:aws:iam::517723527581:role/*InfraDeployRole*",
        "arn:aws:iam::517723527581:role/*DevRole*",
        "arn:aws:iam::517723527581:policy/*HumanAccessBoundary*",
        "arn:aws:iam::517723527581:policy/*InfraDeploy*"
      ]
    },
    {
      "Sid": "NeverIdentityCredentialOrgOrBillingAdministration",
      "Effect": "Deny",
      "Action": [
        "iam:CreateAccessKey",
        "iam:UpdateAccessKey",
        "iam:CreateLoginProfile",
        "iam:UpdateLoginProfile",
        "iam:CreateServiceSpecificCredential",
        "iam:UploadSSHPublicKey",
        "iam:UploadSigningCertificate",
        "iam:CreateVirtualMFADevice",
        "iam:EnableMFADevice",
        "iam:DeactivateMFADevice",
        "iam:CreateSAMLProvider",
        "iam:CreateOpenIDConnectProvider",
        "iam:UpdateAccountPasswordPolicy",
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "iam:PutGroupPolicy",
        "iam:AddUserToGroup",
        "iam:AttachUserPolicy",
        "iam:PutRolePermissionsBoundary",
        "iam:DeleteRolePermissionsBoundary",
        "iam:PutUserPermissionsBoundary",
        "iam:DeleteUserPermissionsBoundary",
        "sso:*",
        "sso-directory:*",
        "identitystore:*",
        "organizations:*",
        "account:*",
        "aws-portal:*",
        "billing:*",
        "ce:*",
        "budgets:*",
        "cur:*",
        "sts:AssumeRole",
        "sts:AssumeRoleWithSAML",
        "sts:AssumeRoleWithWebIdentity",
        "sts:GetFederationToken"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NeverCreatePoliciesOrGroupsOutsideTibanna",
      "Effect": "Deny",
      "Action": [
        "iam:CreatePolicy",
        "iam:CreateGroup",
        "iam:AttachGroupPolicy"
      ],
      "NotResource": [
        "arn:aws:iam::517723527581:policy/tibanna_tiger_*",
        "arn:aws:iam::517723527581:group/tibanna_tiger_*"
      ]
    },
    {
      "Sid": "NeverAttachOtherPoliciesToTibannaRoles",
      "Effect": "Deny",
      "Action": [
        "iam:AttachRolePolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:role/tibanna_tiger_*",
      "Condition": {
        "ArnNotLike": {
          "iam:PolicyARN": [
            "arn:aws:iam::517723527581:policy/tibanna_tiger_*",
            "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
            "arn:aws:iam::aws:policy/AmazonEC2FullAccess",
            "arn:aws:iam::aws:policy/AWSElasticBeanstalkReadOnly",
            "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaRole"
          ]
        }
      }
    },
    {
      "Sid": "NeverAttachOtherPoliciesToTibannaGroups",
      "Effect": "Deny",
      "Action": [
        "iam:AttachGroupPolicy"
      ],
      "Resource": "arn:aws:iam::517723527581:group/tibanna_tiger_*",
      "Condition": {
        "ArnNotLike": {
          "iam:PolicyARN": [
            "arn:aws:iam::517723527581:policy/tibanna_tiger_*",
            "arn:aws:iam::aws:policy/CloudWatchReadOnlyAccess",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
          ]
        }
      }
    },
    {
      "Sid": "NeverLaunchTibannaWorkers",
      "Effect": "Deny",
      "Action": [
        "ec2:RunInstances",
        "ec2:AssociateIamInstanceProfile",
        "ec2:ReplaceIamInstanceProfileAssociation"
      ],
      "Resource": "*",
      "Condition": {
        "ArnLike": {
          "ec2:InstanceProfile": "arn:aws:iam::517723527581:instance-profile/tibanna_tiger_*"
        }
      }
    },
    {
      "Sid": "NeverRunWorkloadsDirectly",
      "Effect": "Deny",
      "Action": [
        "lambda:InvokeFunction",
        "lambda:InvokeFunctionUrl",
        "ecs:RunTask",
        "ecs:StartTask",
        "ecs:ExecuteCommand",
        "codebuild:RetryBuild",
        "codebuild:StartBuildBatch",
        "codebuild:RetryBuildBatch",
        "states:StartExecution",
        "states:StartSyncExecution",
        "states:RedriveExecution",
        "ssm:SendCommand",
        "ssm:StartSession",
        "ec2-instance-connect:SendSSHPublicKey",
        "ecr:BatchDeleteImage",
        "es:ESHttp*",
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NeverDestroyDataBearingResources",
      "Effect": "Deny",
      "Action": [
        "rds:DeleteDBInstance",
        "rds:DeleteDBCluster",
        "rds:DeleteDBSnapshot",
        "rds:DeleteDBClusterSnapshot",
        "es:DeleteDomain",
        "es:DeleteElasticsearchDomain",
        "s3:DeleteBucket",
        "s3:DeleteObject",
        "s3:DeleteObjectVersion",
        "sqs:DeleteQueue",
        "sqs:PurgeQueue",
        "secretsmanager:DeleteSecret",
        "kms:ScheduleKeyDeletion",
        "kms:DisableKey",
        "ecr:DeleteRepository",
        "logs:DeleteLogGroup",
        "elasticache:DeleteReplicationGroup",
        "elasticache:DeleteSnapshot",
        "dynamodb:DeleteTable"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NeverDeleteOtherStacksOrRemoveStackProtections",
      "Effect": "Deny",
      "Action": [
        "cloudformation:DeleteStack",
        "cloudformation:RollbackStack"
      ],
      "NotResource": "arn:aws:cloudformation:us-east-1:517723527581:stack/c4-*/*"
    },
    {
      "Sid": "NeverAdministerStackSetsOrStackProtections",
      "Effect": "Deny",
      "Action": [
        "cloudformation:DeleteStackSet",
        "cloudformation:UpdateTerminationProtection",
        "cloudformation:SetStackPolicy"
      ],
      "Resource": "*"
    },
    {
      "Sid": "NeverWriteSecretValuesExceptTheDatabaseEndpoint",
      "Effect": "Deny",
      "Action": [
        "secretsmanager:PutSecretValue"
      ],
      "NotResource": "arn:aws:secretsmanager:us-east-1:517723527581:secret:C4*RDSSecret*"
    },
    {
      "Sid": "NeverRewriteSecretPayloadsOrPolicies",
      "Effect": "Deny",
      "Action": [
        "secretsmanager:UpdateSecret",
        "secretsmanager:RotateSecret",
        "secretsmanager:PutResourcePolicy",
        "secretsmanager:DeleteResourcePolicy"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyOutsideHomeRegionExceptGlobalServices",
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
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": "us-east-1"
        }
      }
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
