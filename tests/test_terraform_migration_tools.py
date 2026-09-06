"""Offline migration suggestions must be complete, injection-safe, and current-head aware."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "terraform/tools" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_managed_iam_and_flowlog_addresses():
    tool = load_tool("import_from_cfn")
    for logical, suffix in [
        ("ECSSecretManagerPolicy", "ecs_secret_manager"),
        ("ECSESAccessPolicy", "ecs_es"),
        ("ECSSQSAccessPolicy", "ecs_sqs"),
        ("ECSECRPolicy", "ecs_ecr"),
        ("ECSS3Policy", "ecs_s3"),
        ("ECSKMSPolicy", "ecs_kms[0]"),
    ]:
        lines = tool.build_commands(
            "iam",
            "module.iam",
            [
                {
                    "LogicalResourceId": f"C4IAMMain{logical}",
                    "ResourceType": "AWS::IAM::ManagedPolicy",
                    "PhysicalResourceId": "arn:aws:iam::123456789012:policy/synthetic",
                }
            ],
        )
        assert f"module.iam.aws_iam_policy.{suffix}" in "\n".join(lines)
        assert any("attachments" in line for line in lines)
    assert "aws_flow_log.main[0]" in "\n".join(
        tool.build_commands(
            "network",
            "module.network",
            [
                {
                    "LogicalResourceId": "C4NetworkMainVPCFlowLog",
                    "ResourceType": "AWS::EC2::FlowLog",
                    "PhysicalResourceId": "fl-synthetic",
                }
            ],
        )
    )


def test_explicit_variant_mapping_and_duplicate_refusal(tmp_path, capsys):
    tool = load_tool("import_from_cfn")
    records = [
        {
            "LogicalResourceId": "Portal",
            "ResourceType": "AWS::ECS::TaskDefinition",
            "PhysicalResourceId": "arn:task:test",
        }
    ]
    source = tmp_path / "stack.json"
    source.write_text(json.dumps(records))
    args = ["--module", "ecs-app", "--module-address", "module.ecs", "--stack-file", str(source)]
    assert tool.main(args) == 1
    assert "INCOMPLETE" in capsys.readouterr().out
    mapping = tmp_path / "map.json"
    mapping.write_text(json.dumps({"Portal": 'aws_ecs_task_definition.this["standalone-portal"]'}))
    assert tool.main(args + ["--address-map", str(mapping)]) == 0
    output = capsys.readouterr().out
    assert "standalone-portal" in output and "INCOMPLETE" not in output
    with pytest.raises(ValueError, match="Duplicate import address"):
        tool.build_commands("ecs-app", "module.ecs", records * 2, json.loads(mapping.read_text()))


def test_tfvars_retains_postgres_pin_and_inventory_without_secret_values(tmp_path, capsys):
    tool = load_tool("generate_tfvars")
    source = tmp_path / "input.json"
    source.write_text(
        json.dumps(
            {
                "rds.postgres_version": "14.4",
                "app.deploy": "blue/green",
                "iam.ecosystem_resources": {"runtime_secrets": ["fourfront-mastertest"]},
                "GITHUB_PERSONAL_ACCESS_TOKEN": "SYNTHETIC_PAT_MUST_NOT_PRINT",
                "rds.name": 'quote"\nexample',
            }
        )
    )
    assert tool.main(["--config", str(source)]) == 0
    output = capsys.readouterr().out
    assert 'rds_postgres_version = "14.4"' in output
    assert 'deployment_paradigm = "blue_green"' in output
    assert "iam_ecosystem_resources" in output and "fourfront-mastertest" in output
    assert "SYNTHETIC_PAT_MUST_NOT_PRINT" not in output
    assert 'rds_name = "quote\\"\\nexample"' in output
