# `codebuild` — DEFERRED in this PR

CI/build module from `src/parts/codebuild.py`. Not yet implemented; env roots reference it only as
commented `# module "codebuild"` TODOs.

## When implemented, faithful to codebuild.py

- 2–5 per-project `IAM::Role` (a second IAM-authoring location, distinct from iam.py), up to 5
  `CodeBuild::Project` (portal/blue-green, cgap-pipeline, external-pipeline, tibanna-awsf — gated by
  `app_kind`/`app_deployment`), and a `CodeBuild::SourceCredential`.
- **State-exposure gate (why extra care):** the GitHub PAT is embedded in the source credential
  (`codebuild.py:325-332`) → `aws_codebuild_source_credential.token` lands in Terraform STATE. The
  Phase-0 state-bucket hardening (`modules/bootstrap`; SSE-KMS/versioning/TLS-only) must be
  **re-verified** before this module is applied/imported (plan §8.3, §3 Phase 6). Prefer sourcing
  the PAT from Secrets Manager via a `data` source over a tfvars literal.
- Consumes network via `data.terraform_remote_state`; DockerHub creds via `modules/shared-secrets`.
