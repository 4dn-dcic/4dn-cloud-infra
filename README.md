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
`*DevRole` (which trusts the account root and carries ten AWS managed policies plus runtime policies):

| Role | Purpose |
|---|---|
| `*DevDiagnoseRole` | Read-only inspection of the running system |
| `*PowerRemediateRole` | Operational API access, including privileged build/workflow delegation |

They are built by `C4IAM` in `src/parts/iam.py` and live in the IAM stack. With none of the
`human_access.*` settings present in `template.config.json` the IAM template is byte-for-byte what
it was before, and neither role is created unless approved principal ARNs are supplied - there is
no account-root trust fallback. See `docs/source/human_access_roles.rst` for the operator detail.

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
> principal ARNs from `template.config.json`) is not shown here. The three inline policies attached
> to each role are also merged into one document per role for readability.

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
