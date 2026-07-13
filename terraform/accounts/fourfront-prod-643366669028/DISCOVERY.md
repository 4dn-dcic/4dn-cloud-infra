# Phase-0 discovery — fourfront-prod (643366669028) — THE 4dn ACCOUNT

**Not yet run.** This account is special (plan §1.2, §3 Phase 1b):

- The VPC (`vpc-066421dc99161d0ea`, 172.31.0.0/16) is **legacy, unmanaged IT infra** — Terraform
  holds only `network-data` data sources over it. **Do NOT import any networking here.** There is
  no rollback path for this VPC; that is exactly why Terraform never owns it.
- The legacy `c4-network-main-stack` (`cli.py:33`) is the `ImportValue` source for every ff CFN
  deploy — leave it CFN-owned and **frozen** until every ff CFN consumer is migrated, then retire
  it in Phase 7 (its `list-imports`-empty gate genuinely works here — consumers are template-level).
- The account hosts the blue/green pair (`fourfront-production-blue` = today's `4dn-dev`,
  `fourfront-production-green` = today's `4dn-prod`) as two standalone env roots.

```bash
export AWS_PROFILE=<fourfront-prod-profile>
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE \
  --query 'StackSummaries[].StackName' --output table
aws cloudformation describe-stack-resources --stack-name <NAME> ...
# Confirm the legacy VPC/subnet/SG IDs still match the config literals (read-only):
aws ec2 describe-vpcs --vpc-ids vpc-066421dc99161d0ea
```

## Findings (fill in)

| Part | Actual CFN stack name | Scope | Notes |
|---|---|---|---|
| (network) | c4-network-main-stack | shared | **unmanaged legacy VPC — data-only, never import** |
| iam | | shared | pending — wire `modules/iam` after discovery |
| logging | | shared | pending — wire `modules/logging` |
| ecr | | shared | pending — wire `modules/ecr` |
| shared-secrets | | shared | pending — wire `modules/shared-secrets` |
| appconfig (blue) | | env | implemented/wired |
| appconfig (green) | | env | implemented/wired |
| datastore_slim (blue/green) | | env | **DEFERRED** (legacy ES 6.8 variant) |
| fourfront_ecs (blue/green) | | env | **DEFERRED** (ecs-app) |

- [ ] Legacy VPC/subnet/SG IDs re-confirmed against `network-data` inputs
- [ ] `identity_swap.py` (blue/green cutover) verification belongs to this account's track (plan §8.4)
