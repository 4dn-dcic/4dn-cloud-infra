# Phase-0 discovery — smaht-dev (537626822796)

**Not yet run** (this PR performs no AWS access). Populate this file during Phase 0 (plan §3), before
writing any import manifest. Physical stack/resource names come from AWS, **never** derived from
config (plan §1.1 qualifier nuance).

```bash
export AWS_PROFILE=<smaht-dev-profile>
# 1. Every live stack (the ground truth for which SHARING qualifier each shared stack carries):
aws cloudformation list-stacks \
  --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE UPDATE_ROLLBACK_COMPLETE \
  --query 'StackSummaries[].StackName' --output table

# 2. Per stack, the physical-ID inventory that becomes the import manifest:
aws cloudformation describe-stack-resources --stack-name <NAME> \
  --query 'StackResources[].[LogicalResourceId,PhysicalResourceId,ResourceType]' --output table \
  > ../../tools/fixtures/<part>.json   # (JSON form: drop --query/--output for import_from_cfn.py)
```

## Findings (fill in)

| Part | Actual CFN stack name | SHARING qualifier | Notes |
|---|---|---|---|
| network | _e.g. c4-network-main-stack_ | main | ecosystem |
| iam | | | |
| logging | | | |
| ecr | | | |
| shared-secrets | | | |
| appconfig (smaht-wolf) | | | env |
| datastore (smaht-wolf) | | | env; blocks §2.3 consumers |
| ecs (smaht-wolf) | | | which variant is live? |
| redis (smaht-wolf) | | | |

- [ ] `subnet.pair_count` confirmed live (config says 6)
- [ ] ECS variant per env recorded (standalone vs blue/green — drives shared-vs-env root, plan §5.1)
- [ ] `datastore_slim` live anywhere? (expected: no, smaht account)
