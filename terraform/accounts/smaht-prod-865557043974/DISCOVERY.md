# Phase-0 discovery — smaht-prod (865557043974)

**Not yet run.** Same procedure as `../smaht-dev-537626822796/DISCOVERY.md`. Run against the
smaht-prod profile before any import manifest. Names from AWS, never from config (plan §1.1).

## Findings (fill in)

| Part | Actual CFN stack name | SHARING qualifier | Notes |
|---|---|---|---|
| network | | main | ecosystem |
| iam | | | |
| logging | | | |
| ecr | | | |
| shared-secrets | | | |
| appconfig (production) | | | env |
| datastore (production) | | | env; blocks §2.3 consumers |
| ecs (production) | | | variant? sizing from config: wsgi 4096/8192, indexer 256/512 |
| redis (production) | | | |
| sentieon (production) | | | ec2-service implemented; wiring/adoption pending; sentieon.ssh_key set |

- [ ] ECS variant recorded
- [ ] `datastore_slim` live anywhere? (expected: no)
