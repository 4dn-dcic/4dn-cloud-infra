# Current resource/configuration contract

Ground truth: current `src/parts/`, including the PR97 B1–B6/N2 corrections and merged PR100.
The comparison is by resource graph and configuration, **not filename translation**.
`tests/test_terraform_parity.py` evaluates native mock-provider plans against complete synthesized
Troposphere templates; `tests/test_stack_regressions.py` retains the independent CFN regressions.

| Contract | Native implementation / deterministic comparison |
|---|---|
| B1 TLS and startup | `ecs-app`: all standalone CGAP/Fourfront/SMaHT, standard/SRCE and two-color variants. HTTP forwarding without a certificate; otherwise TLS 1.2/1.3 HTTPS forwarding + HTTP 301 redirect. Every service depends on the **forwarding** listener, verified with Terraform's dependency graph and target associations. |
| ECS task/runtime | Full container JSON, task CPU/memory, identities, image tags, log groups/prefixes, task volumes, service counts/capacity strategies and variant resource counts. Fourfront standalone has four tasks/two services/no alarms; generic standalone five/three/four; blue/green ten/six/four. Falcon is optional, nonessential, CID-only, read/write preparation vs read-only app mount, loader entrypoint and SUCCESS dependency. |
| B2 shared IAM | Required six-class exact inventory, account/region-local ARNs, legacy `es-` domains/Fourfront identities/SRCE DB names, exact six-character secret ARN suffix. Two-environment comparison follows managed-policy attachments, verifies quotas, denials and that selecting another env cannot replace permissions. Empty KMS inventory is explicit bootstrap, never `Resource:*`. |
| B3 PostgreSQL | One input drives engine and parameter family in standard/SRCE/slim; unset=17.6, explicit 14.4/16.6/17.6 retained, both paradigms. No instance-only version override or forced major upgrade. Root inputs and tfvars suggestions retain explicit pins. |
| Datastore | RDS properties, SSL parameter, private subnet/SG inputs, credential metadata, standalone/two-color OpenSearch vs legacy slim Elasticsearch. Bucket names, public blocking, versioning, full lifecycle rules and encryption-denial policies are compared; encryption on/off retains the SSE-S3 system bucket. Five queues' encryption, timing and retention properties are compared. |
| B4 FlowLog IAM | Standard network owns FlowLog + delivery IAM + retained log group, with enable/disable and complete trust/delivery-policy parity. Native Terraform needs no CFN capabilities flag; its role reference orders the FlowLog. The retained CLI independently derives CAPABILITY_IAM from synthesized resources. SRCE has no repository-managed FlowLogs. |
| B5 CodeBuild VPC | Explicit SRCE Application network wins even when a standard network is present. Projects use its VPC, first private subnet and Application SG, never DB/Compute. Source CLI producer/export closure tests remain. SRCE shell outputs expose typed Application/Database/Compute contracts. |
| B6 build authority | Project -> actual role -> complete policy/environment comparison for CGAP/Fourfront/SMaHT and standalone/two-color. Only first-party pipeline gets Falcon API secrets. Portal/external/Tibanna get DockerHub only. No broad runtime secret prefix. No secrets are resolved in Terraform configuration. |
| PR100 / Foursight | Complete portal/Foursight initial JSON compared, including the five concrete bucket values matching datastore producers. Root wiring passes actual bucket outputs. `foursight_secret_name` and the SRCE example expose identity and Application-only metadata; the retained Python package path selects `foursight_smaht`. |
| SRCE shells / auxiliary compute | Three existing VPCs, seven owned SGs, exact directional protocol/port/CIDR rule comparison, subnet disjointness. Compute retained. EC2 Higlass/JupyterHub user data and default instance/LB/rule contracts; standard/SRCE Sentieon admin/VPC/Compute license rules. Optional standard bastion skips incomplete/off configurations. |
| Other foundations | ECR/logging/shared-secret implementations retain the current contracts. Redis encryption, engine/node/failover options are compared; discovered replication-group ID is supported. Bootstrap is new state infrastructure, not a migrated CFN resource. |
| N2 validation / tooling | No forced TTY; schema/init/lint child errors propagate, including a failed init preventing validation. Parent success is never printed on failure. CFN validation/package/change-set failure tests remain. Exact import maps reject duplicate targets and incomplete suggestions exit nonzero. |

## Local validation evidence

Against PR97 `d7ba6e9` (including merged PR100), merged into PR98 without rewriting either head:

| Safe check | Result |
|---|---|
| Full locked Python suite + native plan-only mock matrix | **313 passed**, three dependency/deprecation warnings; includes 80 native parity cases |
| Terraform 1.15.8 `validate.sh schema` | **47 checks passed**: formatting plus backend-disabled init/validate for 23 roots/modules/examples |
| TFLint 0.53.0 `validate.sh lint` | **23 passed** |
| Changed Python files, flake8 (120-column limit); shell syntax; `git diff --check` | Passed |
| cfn-lint 0.86.4, 134 deduplicated synthetic templates | **0 errors, 319 warnings**, exit 4: W2001=41, W3010=47, W3045=210, W3005=3, W3011=18 |
| Checkov 3.2.471, modules, `--skip-download` | **386 passed, 106 failed, 0 parsing errors**, exit 1; advisory findings, not a clean security result |

Checkov findings include inherited IAM management wildcards, auxiliary HTTP/public-instance
behavior, egress, log/secret encryption and retention defaults, and availability/monitoring
hardening. They are not suppressed or used to silently change the migration contract. Source CFN
warnings cover parameters, AZs, legacy bucket ACLs, explicit dependencies and retention attributes.
Neither offline validity nor these advisory results establish deployability or runtime safety.

## Native representation differences (review before adoption)

- CFN `Ref`/`ImportValue` becomes typed module inputs/outputs. Native outputs do **not** keep CFN
  exports alive. Python runtime discovery and Chalice/Foursight remain CFN consumers until repointed.
- ECS capacity-provider associations and IAM managed-policy attachments are separate native
  resources. CFN SGs with **separate** egress resources retain EC2's default all-egress rule;
  native modules explicitly preserve it. This is not evidence of restrictive egress. EC2 web
  service LB groups with inline egress keep only their explicit rules.
- Terraform requires explicit ECS families/service names, Redis IDs, and other names where CFN
  generates them. Defaults are for new resources, **not discovery**. Supply discovered overrides
  before adoption. Preserve tags too; test comparisons do not assert account-specific tags or
  generated physical IDs. Redis new-resource IDs are lowercase, as its API requires.
- IAM data policies use customer-managed resources as in corrected CFN; developer role policies
  remain inline (its ten AWS-managed attachments are retained). Native policies combine statements
  for each CodeBuild role without changing actions/resources. CodeBuild GitHub credentials are an
  **account singleton**, isolated in `codebuild-credentials`, not duplicated per project/env.
  Its sensitive create-only token requires encrypted state and is ignored after adoption.
- RDS SecretTargetAttachment is represented by the native secret JSON's engine/host/port/dbname/
  instance identifier, with credentials generated only for new resources. Existing versions and
  RDS passwords are ignored after adoption. Endpoint/credential reconciliation remains operational.
- Slim uses the shared datastore module with `variant="slim"`: no bucket/queue/KMS ownership,
  legacy `es-` names, Elasticsearch 6.8, gp2/10-GiB default. It retains Terraform migration safety
  gates (deletion protection and seven-day backups) even though legacy CFN slim omitted them;
  these are explicit reviewed differences, **not a no-op-plan claim**.
- Native optional task sizing/count and EC2 instance-type inputs honor explicit values. Some
  legacy blue/green/EC2 factory argument defaults mask those config overrides; default shapes
  remain compared. Existing standalone empty-indexer alarm queue double-dash naming is preserved,
  not silently redefined in a migration. Auxiliary web ALBs remain HTTP and require manual
  target registration as in CFN; portal TLS does not imply auxiliary TLS.
- Native CodeBuild logs additionally use `prevent_destroy` for adoption safety. Datastore no longer
  invents an extra KMS alias absent from CFN. KMS use still requires actual principal/key-policy
  evidence. Central IT owns CloudTrail; no trail is added.

## Import completeness

`import_from_cfn.py --address-map map.json` accepts **relative native addresses**, for example:

```json
{
  "CgapbluePortal": "aws_ecs_task_definition.this[\"blue-portal\"]",
  "CgapbluePortalService": "aws_ecs_service.this[\"blue-portal\"]"
}
```

Use real saved logical IDs, not these illustrative names. A physical CFN resource can fan out
into native satellites that do not appear in stack-resource inventories. Adopt those separately:

- every Secrets Manager **version**, as warned after each container suggestion;
- IAM role/user inline policies (`<identity>:<policy-name>`) and managed attachments
  (`<identity>/<policy-arn>`). Shared data attachments are `ecs_data[secrets|es|sqs|ecr|s3|kms]`,
  federator attachments `s3_federator_s3` / `s3_federator_kms[0]`; preserve discovered policy names;
- ECS cluster capacity-provider associations, SG rules/default egress, subnet/route associations;
- S3 versioning, public-access blocking, encryption and lifecycle resources (bucket-name import IDs).

A CodeBuild source credential found in an environment CFN stack must be inventoried/adopted once
into the **shared** credential root, with the environment projects consuming its ARN. Do not force
an address from one root into another. Unmapped rows are stop signals, not permission to drop them.

No-op adoption, schema validity, IAM authorization, routing and runtime health are separate claims.
The offline suite establishes only the resource/configuration comparisons described above.
