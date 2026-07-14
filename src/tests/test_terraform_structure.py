"""
Structural tests for the terraform/ tree (Troposphere -> Terraform migration).

These are pure-filesystem / text tests — they do NOT run terraform and import nothing from the
Troposphere codebase, so they add no dependencies and run under `make test` unchanged. They guard
the SHARING invariant (plan §1.1): a module's Terraform root must match its SHARING scope, so no
physical resource can ever be owned by two Terraform states.
"""
import importlib.util
import os
import re

import pytest

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TF_ROOT = os.path.join(REPO_ROOT, "terraform")

# Modules whose CFN inventory includes a secretsmanager secret (container + *_version pair) and
# so must carry the *_version import-safety adoption (see import_from_cfn.py's SAFETY docstring).
SECRET_BEARING_MODULES = {"datastore", "shared-secrets", "appconfig"}

# Implemented modules that are NEVER imported from CFN: bootstrap is fresh local state;
# network-data/srce-network are data-source-only wrappers over externally-owned VPCs.
NEVER_IMPORTED_MODULES = {"bootstrap", "network-data", "srce-network"}


def _load_import_tool():
    """Load terraform/tools/import_from_cfn.py as a module (it's a standalone script, not a package)."""
    path = os.path.join(TF_ROOT, "tools", "import_from_cfn.py")
    spec = importlib.util.spec_from_file_location("import_from_cfn", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# SHARING scope of each module (from src/parts/*.py; see plan §1.1 / §2.1).
ECOSYSTEM_MODULES = {"network", "network-data", "iam", "ecr", "logging", "shared-secrets", "srce-network"}
ENV_MODULES = {"appconfig", "datastore", "datastore-slim", "redis", "ecs-app", "codebuild", "ec2-service"}

# Modules actually implemented in this PR (deferred ones are README-only, no .tf).
IMPLEMENTED_MODULES = {
    "bootstrap", "network", "network-data", "iam", "ecr", "logging", "shared-secrets",
    "appconfig", "datastore", "redis", "srce-network",
}

MODULE_SOURCE_RE = re.compile(r'source\s*=\s*"((?:\.\./)+modules/([a-z0-9-]+))"')


def _tf_available():
    return os.path.isdir(TF_ROOT)


pytestmark = pytest.mark.skipif(not _tf_available(), reason="terraform/ tree not present")


def _root_dirs():
    """Every account root (a dir containing a main.tf under accounts/)."""
    roots = []
    accounts = os.path.join(TF_ROOT, "accounts")
    for dirpath, _dirs, files in os.walk(accounts):
        if "main.tf" in files:
            roots.append(dirpath)
    return roots


def _module_sources(main_tf_path):
    """Return the list of ACTIVE (non-commented) module source basenames referenced in a root."""
    out = []
    with open(main_tf_path) as f:
        for line in f:
            if line.lstrip().startswith("#"):
                continue  # skip commented-out (deferred) module blocks
            m = MODULE_SOURCE_RE.search(line)
            if m:
                out.append(m.group(2))
    return out


def test_module_dirs_have_required_files():
    """Every implemented module has main.tf + variables.tf + outputs.tf + versions.tf."""
    for name in IMPLEMENTED_MODULES:
        mdir = os.path.join(TF_ROOT, "modules", name)
        assert os.path.isdir(mdir), f"missing module dir: {name}"
        for fn in ("main.tf", "variables.tf", "outputs.tf", "versions.tf"):
            # bootstrap has no variables-less exception; all four expected
            assert os.path.isfile(os.path.join(mdir, fn)), f"{name} missing {fn}"


def test_shared_roots_only_instantiate_ecosystem_modules():
    """SHARING invariant: shared/ roots may only call ecosystem-scoped modules (plan §1.1)."""
    for root in _root_dirs():
        if os.path.basename(root) != "shared":
            continue
        for src in _module_sources(os.path.join(root, "main.tf")):
            assert src in ECOSYSTEM_MODULES, (
                f"shared root {root} instantiates non-ecosystem module {src!r} "
                f"(would violate the SHARING scope split)"
            )


def test_env_roots_only_instantiate_env_modules():
    """SHARING invariant: envs/<env>/ roots may only call env-scoped modules (plan §1.1)."""
    for root in _root_dirs():
        # env roots live under .../envs/<env>
        if os.path.basename(os.path.dirname(root)) != "envs":
            continue
        for src in _module_sources(os.path.join(root, "main.tf")):
            assert src in ENV_MODULES, (
                f"env root {root} instantiates non-env module {src!r} "
                f"(ecosystem-shared resources must live in shared/, not per-env)"
            )


def test_fourfront_account_never_uses_managed_network():
    """The 4dn account's VPC is unmanaged legacy infra: it must use network-data, never network."""
    ff_shared = os.path.join(TF_ROOT, "accounts", "fourfront-prod-643366669028", "shared", "main.tf")
    assert os.path.isfile(ff_shared)
    srcs = _module_sources(ff_shared)
    assert "network" not in srcs, "4dn account must NOT import the managed network module (plan §3 Phase 1b)"
    assert "network-data" in srcs, "4dn account shared root must use the network-data module"


def test_no_ecosystem_module_instantiated_in_two_roots_per_account():
    """No ecosystem module may appear in more than one root within the same account (no double-import)."""
    accounts = os.path.join(TF_ROOT, "accounts")
    for account in sorted(os.listdir(accounts)):
        adir = os.path.join(accounts, account)
        if not os.path.isdir(adir):
            continue
        seen = {}
        for root in _root_dirs():
            if not root.startswith(adir + os.sep):
                continue
            for src in _module_sources(os.path.join(root, "main.tf")):
                if src in ECOSYSTEM_MODULES:
                    seen.setdefault(src, []).append(root)
        for src, roots in seen.items():
            assert len(roots) == 1, (
                f"ecosystem module {src!r} instantiated in {len(roots)} roots of account "
                f"{account}: {roots} — violates the single-owner SHARING invariant"
            )


def test_log_groups_have_prevent_destroy():
    """Safety gate: log groups in logging + network modules must carry prevent_destroy (plan §4.3, §6.2)."""
    for mod in ("logging", "network"):
        main = os.path.join(TF_ROOT, "modules", mod, "main.tf")
        text = open(main).read()
        assert "aws_cloudwatch_log_group" in text, f"{mod} should manage a log group"
        assert "prevent_destroy = true" in text, f"{mod} log group missing prevent_destroy safety gate"


def test_gac_secret_has_ignore_changes():
    """Safety gate: appconfig GAC secret version must ignore_changes on secret_string (plan §5.3, §8.3)."""
    text = open(os.path.join(TF_ROOT, "modules", "appconfig", "main.tf")).read()
    assert "ignore_changes = [secret_string]" in text


def test_rds_deletion_protection():
    """Safety gate: datastore RDS instance keeps deletion_protection = true (datastore.py:566)."""
    text = open(os.path.join(TF_ROOT, "modules", "datastore", "main.tf")).read()
    assert "deletion_protection     = true" in text or "deletion_protection = true" in text


def test_state_bucket_hardening():
    """Safety gate: bootstrap state bucket has SSE-KMS, versioning, public-access block, TLS-only (plan §8.3)."""
    text = open(os.path.join(TF_ROOT, "modules", "bootstrap", "main.tf")).read()
    assert "aws_s3_bucket_versioning" in text
    assert "aws_s3_bucket_public_access_block" in text
    assert "aws:kms" in text
    assert "aws:SecureTransport" in text


def test_every_secret_version_has_ignore_changes():
    """HIGH safety gate: every aws_secretsmanager_secret_version in every secret-bearing module
    must carry ignore_changes = [secret_string] — Terraform must never manage live secret content,
    including the RDS master password in modules/datastore (plan §5.3, §7.4, §8.3)."""
    for mod in sorted(SECRET_BEARING_MODULES):
        with open(os.path.join(TF_ROOT, "modules", mod, "main.tf")) as f:
            code_lines = [line for line in f if not line.lstrip().startswith("#")]
        text = "".join(code_lines)
        version_count = text.count('resource "aws_secretsmanager_secret_version"')
        ignore_count = text.count("ignore_changes = [secret_string]")
        assert version_count > 0, f"{mod} was expected to manage a secretsmanager secret version"
        assert ignore_count == version_count, (
            f"{mod}: {version_count} aws_secretsmanager_secret_version resource(s) but only "
            f"{ignore_count} carry ignore_changes = [secret_string] — every one must, or Terraform "
            f"can overwrite live secret content on the next apply"
        )


def test_import_tool_covers_every_module_requiring_import():
    """MEDIUM safety gate: import_from_cfn.py must cover every implemented module that will
    require a CFN import, not just the original network/datastore examples."""
    tool = _load_import_tool()
    requires_import = IMPLEMENTED_MODULES - NEVER_IMPORTED_MODULES
    missing = requires_import - set(tool.SUPPORTED)
    assert not missing, (
        f"import_from_cfn.py has no coverage for implemented, import-requiring module(s): "
        f"{sorted(missing)} — add a rule function and register it in SUPPORTED/build_commands"
    )
    # And nothing in SUPPORTED claims coverage for a module that's actually never imported.
    stale = set(tool.SUPPORTED) & NEVER_IMPORTED_MODULES
    assert not stale, f"import_from_cfn.py lists never-imported module(s) as supported: {sorted(stale)}"


def test_import_tool_emits_secret_version_adoption_warning():
    """HIGH safety gate, exercised end-to-end: for every secret-bearing module, running the import
    tool against a AWS::SecretsManager::Secret resource must ALWAYS emit the ACTION-REQUIRED
    *_version adoption block — silently importing only the container is the exact gap that lets
    `terraform apply` overwrite a live secret (including the RDS password) right after import."""
    tool = _load_import_tool()
    fixture_logical_ids = {
        "datastore": "C4DatastoreSmahtWolfRDSSecret",
        "shared-secrets": "DockerHubSecret",
        "appconfig": "C4AppConfigSmahtWolf",
    }
    for mod in sorted(SECRET_BEARING_MODULES):
        resources = [{
            "LogicalResourceId": fixture_logical_ids[mod],
            "PhysicalResourceId": "arn:aws:secretsmanager:us-east-1:111111111111:secret:test-abc123",
            "ResourceType": "AWS::SecretsManager::Secret",
        }]
        lines = tool.build_commands(mod, f"module.{mod.replace('-', '_')}", resources)
        output = "\n".join(lines)
        assert "aws_secretsmanager_secret_version" in output, (
            f"{mod}: import tool did not resolve the secret container for its own fixture"
        )
        assert "ACTION-REQUIRED" in output, (
            f"{mod}: import tool did not emit the mandatory *_version adoption warning"
        )
        assert "list-secret-version-ids" in output


def test_datastore_import_fixture_still_triggers_secret_version_warning():
    """Regression pin: the shipped datastore.json fixture (used in README examples) must keep
    surfacing the RDS secret-version adoption warning."""
    tool = _load_import_tool()
    fixture = os.path.join(TF_ROOT, "tools", "fixtures", "datastore.json")
    import json
    with open(fixture) as f:
        resources = json.load(f)["StackResources"]
    lines = tool.build_commands("datastore", "module.datastore", resources)
    output = "\n".join(lines)
    assert "aws_secretsmanager_secret_version.rds" in output
    assert "ACTION-REQUIRED" in output
