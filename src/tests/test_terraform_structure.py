"""
Structural tests for the terraform/ tree (Troposphere -> Terraform migration).

These are pure-filesystem / text tests — they do NOT run terraform and import nothing from the
Troposphere codebase, so they add no dependencies and run under `make test` unchanged. They guard
the SHARING invariant (plan §1.1): a module's Terraform root must match its SHARING scope, so no
physical resource can ever be owned by two Terraform states.
"""
import os
import re

import pytest

HERE = os.path.dirname(__file__)
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
TF_ROOT = os.path.join(REPO_ROOT, "terraform")

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
