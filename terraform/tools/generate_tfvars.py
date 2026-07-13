#!/usr/bin/env python3
"""
generate_tfvars.py — transform a custom_directories/<env>/template.config.json into suggested
Terraform tfvars, partitioned by scope (plan §5.3): account-level keys -> the shared/ root,
env-level keys -> the envs/<env>/ root.

OFFLINE and read-only: reads the JSON config, prints suggestions to stdout. It NEVER emits secret
values — secret keys (Auth0, PAT, S3_ENCRYPT_KEY, reCaptcha) are intentionally skipped; those stay
in Secrets Manager and are referenced via `data` sources (plan §5.3, §8.3). Review the output before
committing anything; real physical names (buckets, stacks) still come from Phase-0 discovery.

Usage:
    python3 generate_tfvars.py --config ../../custom_directories/smaht-wolf/template.config.json
"""
import argparse
import json
import sys

# Non-secret config keys we surface, grouped by the scope of the module that consumes them.
SHARED_KEYS = {
    "app.kind": "app_kind",
    "subnet.pair_count": "subnet_pair_count",
    "s3.encrypt_key_id": "s3_encrypt_key_id",
}
ENV_KEYS = {
    "ENCODED_ENV_NAME": "env_name",
    "app.deploy": "deployment_paradigm",
    "s3.bucket.encryption": "s3_bucket_encryption",
    "s3.bucket.org": "s3_bucket_org",
    "rds.name": "rds_name",
    "rds.instance_size": "rds_instance_class",
    "rds.storage_size": "rds_allocated_storage",
    "rds.az": "rds_availability_zone",
    "GLOBAL_ENV_BUCKET": "global_env_bucket",
    "elasticsearch.data_node_type": "es_data_node_type",
    "elasticsearch.volume_size": "es_volume_size",
}
# 4dn-only legacy-VPC keys -> the shared/ network-data root.
FOURFRONT_KEYS = {
    "fourfront.vpc": "fourfront_vpc_id",
    "fourfront.rds.sg": "fourfront_rds_sg_id",
    "fourfront.https.sg": "fourfront_https_sg_id",
}
# Never emitted (kept in Secrets Manager).
SECRET_KEYS = {"Auth0Client", "Auth0Secret", "reCaptchaKey", "reCaptchaSecret",
               "GITHUB_PERSONAL_ACCESS_TOKEN", "S3_ENCRYPT_KEY"}


def _emit(title, mapping, config):
    print(f"# --- {title} ---")
    for cfg_key, tf_var in mapping.items():
        if cfg_key in config:
            v = config[cfg_key]
            rendered = json.dumps(v) if not isinstance(v, str) else f'"{v}"'
            print(f"{tf_var} = {rendered}")
    if "fourfront.vpc.subnet_a" in config or "fourfront.vpc.subnet_b" in config:
        subs = [config[k] for k in ("fourfront.vpc.subnet_a", "fourfront.vpc.subnet_b") if k in config]
        if title.startswith("shared") and subs:
            print(f"fourfront_subnet_ids = {json.dumps(subs)}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True, help="path to custom_directories/<env>/template.config.json")
    args = ap.parse_args(argv)
    with open(args.config) as f:
        config = json.load(f)

    dropped = sorted(k for k in config if k in SECRET_KEYS)
    print(f"# Suggested tfvars from {args.config}")
    print("# Review before committing. Secrets are NOT emitted; real names come from discovery.\n")
    _emit("shared/ root (account/ecosystem-scoped)", {**SHARED_KEYS, **FOURFRONT_KEYS}, config)
    _emit("envs/<env>/ root (env-scoped)", ENV_KEYS, config)
    if dropped:
        print(f"# Skipped secret keys (keep in Secrets Manager): {', '.join(dropped)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
