#!/usr/bin/env python3
"""
import_from_cfn.py — generate `terraform import` commands from a saved CloudFormation
describe-stack-resources JSON (plan §4.2, the scripted import approach).

This is DELIBERATELY OFFLINE: it reads a JSON file you captured earlier with

    aws cloudformation describe-stack-resources --stack-name <DISCOVERED-NAME> \
        > terraform/tools/fixtures/<part>.json

and emits, on stdout, the `terraform import <tf-address> <physical-id>` commands that map each
CFN LogicalResourceId to its Terraform address inside the given module. It makes NO AWS calls and
needs no credentials — run it against the saved file, review the commands, then run them yourself
in the target root (per the retain-and-adopt discipline, plan §4.3).

Why scripted-but-imperative (not Terraform `import {}` blocks): plan §4.2 — the imperative command
plus iterative `terraform plan` surfaces exactly which HCL attributes are wrong, one at a time,
which is the safer workflow for a large unfamiliar inventory.

IMPORTANT: stack names and physical IDs come from Phase-0 DISCOVERY, never from config-derived
names (plan §1.1 qualifier nuance). The CFN stack is the import manifest.

Usage:
    python3 import_from_cfn.py --module network \
        --module-address module.network \
        --stack-file fixtures/network.json

    # list supported modules and their mapping rules:
    python3 import_from_cfn.py --list

Supported modules ship faithful mappings for the modules implemented in this PR. Resources with no
rule are emitted as commented "# TODO(no-rule)" lines with their type — never silently dropped
(plan "no silent caps").
"""
import argparse
import json
import re
import sys


def _subnet_address(prefix, logical_id):
    """Map a CFN subnet LogicalResourceId (e.g. ...PrivateSubnetA...) to the module's for_each key."""
    m = re.search(r"(Private|Public)Subnet([A-F])", logical_id)
    if not m:
        return None
    kind = m.group(1).lower()  # private|public
    key = f"{m.group(1)}Subnet{m.group(2)}"  # PrivateSubnetA
    return f'{prefix}.aws_subnet.{kind}["{key}"]'


def _sg_address(prefix, logical_id):
    lid = logical_id.lower()
    if "dbsecuritygroup" in lid or "dbsg" in lid:
        return f"{prefix}.aws_security_group.db"
    if "httpssecuritygroup" in lid or "httpssg" in lid:
        return f"{prefix}.aws_security_group.https"
    if "applicationsecuritygroup" in lid or "appsecuritygroup" in lid:
        return f"{prefix}.aws_security_group.application"
    return None


def _route_table_address(prefix, logical_id):
    lid = logical_id.lower()
    if "mainroutetable" in lid:
        return f"{prefix}.aws_route_table.main"
    if "privateroutetable" in lid:
        return f"{prefix}.aws_route_table.private"
    if "publicroutetable" in lid:
        return f"{prefix}.aws_route_table.public"
    return None


def _endpoint_address(prefix, logical_id):
    lid = logical_id.lower()
    interface_keys = {
        "sqs": "sqs", "ecrapi": "ecrapi", "ecrdkr": "ecrdkr", "secretsmanager": "secretsmanager",
        "ssm": "ssm", "logs": "logs", "ec2": "ec2", "ebs": "ebs", "lambda": "lambda", "states": "states",
    }
    gateway_keys = {"dynamodb": "dynamodb", "s3": "s3"}
    for token, key in interface_keys.items():
        if f"{token}vpciendpoint" in lid or f"{token}endpoint" in lid and "vpcg" not in lid:
            return f'{prefix}.aws_vpc_endpoint.interface["{key}"]'
    for token, key in gateway_keys.items():
        if f"{token}vpcgendpoint" in lid:
            return f'{prefix}.aws_vpc_endpoint.gateway["{key}"]'
    return None


def _bucket_key(logical_id):
    lid = logical_id.lower()
    order = [
        ("metadata", "metadata_bundles"), ("tibannaoutput", "tibanna_output"),
        ("tibannacwl", "tibanna_cwl"), ("blob", "blobs"), ("wfout", "wfout"),
        ("system", "system"), ("file", "files"),
        ("foursightenv", "fs_envs"), ("foursightresult", "fs_results"),
        ("foursightapplicationversion", "fs_app_versions"),
    ]
    for token, key in order:
        if token in lid:
            return key
    return None


NETWORK_RULES = {
    "AWS::EC2::VPC": lambda p, l: f"{p}.aws_vpc.main",
    "AWS::EC2::InternetGateway": lambda p, l: f"{p}.aws_internet_gateway.main",
    "AWS::EC2::NatGateway": lambda p, l: f"{p}.aws_nat_gateway.main",
    "AWS::EC2::EIP": lambda p, l: f"{p}.aws_eip.nat",
    "AWS::EC2::Subnet": _subnet_address,
    "AWS::EC2::SecurityGroup": _sg_address,
    "AWS::EC2::RouteTable": _route_table_address,
    "AWS::EC2::VPCEndpoint": _endpoint_address,
    "AWS::Logs::LogGroup": lambda p, l: f"{p}.aws_cloudwatch_log_group.flow_log[0]",
    "AWS::IAM::Role": lambda p, l: f"{p}.aws_iam_role.flow_log[0]",
    # NOTE: SecurityGroupIngress/Egress + SubnetRouteTableAssociation + VPCGatewayAttachment are
    # modeled differently in TF (rule for_each / implicit attachment) — mapped as TODO below.
}


def _datastore_address(prefix, logical_id, res_type):
    lid = logical_id.lower()
    if res_type == "AWS::RDS::DBInstance":
        return f"{prefix}.aws_db_instance.rds"
    if res_type == "AWS::RDS::DBParameterGroup":
        return f"{prefix}.aws_db_parameter_group.rds"
    if res_type == "AWS::RDS::DBSubnetGroup":
        return f"{prefix}.aws_db_subnet_group.rds"
    if res_type == "AWS::SecretsManager::Secret":
        return f"{prefix}.aws_secretsmanager_secret.rds"
    if res_type == "AWS::KMS::Key":
        return f"{prefix}.aws_kms_key.s3[0]"
    if res_type == "AWS::OpenSearchService::Domain" or res_type == "AWS::Elasticsearch::Domain":
        if "blue" in lid:
            return f'{prefix}.aws_opensearch_domain.this["blue"]'
        if "green" in lid:
            return f'{prefix}.aws_opensearch_domain.this["green"]'
        return f'{prefix}.aws_opensearch_domain.this["default"]'
    if res_type == "AWS::SQS::Queue":
        for token, key in [("secondary", "secondary"), ("dlq", "dlq"), ("ingestion", "ingestion"),
                           ("realtime", "realtime"), ("primary", "primary")]:
            if token in lid:
                return f'{prefix}.aws_sqs_queue.this["{key}"]'
        return None
    if res_type == "AWS::S3::Bucket":
        key = _bucket_key(logical_id)
        return f'{prefix}.aws_s3_bucket.this["{key}"]' if key else None
    if res_type == "AWS::S3::BucketPolicy":
        key = _bucket_key(logical_id)
        return f'{prefix}.aws_s3_bucket_policy.force_encryption["{key}"]' if key else None
    return None


def datastore_rule(prefix, logical_id, res_type):
    return _datastore_address(prefix, logical_id, res_type)


def build_commands(module, prefix, resources):
    lines = []
    for r in resources:
        logical = r["LogicalResourceId"]
        physical = r.get("PhysicalResourceId", "")
        rtype = r["ResourceType"]
        addr = None
        if module == "network":
            fn = NETWORK_RULES.get(rtype)
            if fn:
                addr = fn(prefix, logical)
        elif module == "datastore":
            addr = datastore_rule(prefix, logical, rtype)
        else:
            addr = None
        if addr and physical:
            lines.append(f"terraform import '{addr}' '{physical}'")
        else:
            reason = "no-rule" if not addr else "no-physical-id"
            lines.append(f"# TODO({reason}): {rtype}  logical={logical}  physical={physical!r}")
    return lines


SUPPORTED = {
    "network": "VPC/IGW/NAT/EIP/subnets/route-tables/SGs/endpoints/flow-log group+role",
    "datastore": "RDS/param-group/subnet-group/secret/KMS/OpenSearch/SQS/S3 buckets+policies",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--module", help="module name (see --list)")
    ap.add_argument("--module-address", dest="prefix", help="TF module address, e.g. module.network")
    ap.add_argument("--stack-file", help="path to a saved describe-stack-resources JSON")
    ap.add_argument("--list", action="store_true", help="list supported modules and exit")
    args = ap.parse_args(argv)

    if args.list:
        print("Supported modules:")
        for k, v in SUPPORTED.items():
            print(f"  {k:12s} {v}")
        return 0

    if not (args.module and args.prefix and args.stack_file):
        ap.error("--module, --module-address and --stack-file are required (or use --list)")

    if args.module not in SUPPORTED:
        ap.error(f"unsupported module {args.module!r}; supported: {', '.join(SUPPORTED)}")

    with open(args.stack_file) as f:
        doc = json.load(f)
    resources = doc.get("StackResources", doc if isinstance(doc, list) else [])

    print(f"# terraform import commands for module={args.module} address={args.prefix}")
    print(f"# source: {args.stack_file}  ({len(resources)} CFN resources)")
    print("# Review each line, then run inside the target root. Verify a no-op plan after (plan §4.4).")
    for line in build_commands(args.module, args.prefix, resources):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
