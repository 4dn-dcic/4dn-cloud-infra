# codebuild

Native environment-scoped projects, per-role policies and retained log groups.
Explicit `srce_application_network` wins over `standard_network`, including mixed accounts.
Only the first-party pipeline role receives Falcon API secret ARNs; the portal, external and
Tibanna roles receive DockerHub credentials only. Terraform never retrieves their values.

Consume an existing account GitHub SourceCredential ARN from the shared `codebuild-credentials`
module. Preserve/import existing `/aws/codebuild/<project>` groups and role names before adoption.
See `terraform/PARITY.md`, `examples/srce/main.tf`, and `tests/test_terraform_parity.py`.
