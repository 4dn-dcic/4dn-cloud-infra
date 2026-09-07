"""Native mock-provider plans compared with FULL current Troposphere templates.

Run the offline validation commands in terraform/README.md (including temporary-parent setup).
No Terraform real-provider plan/apply, AWS discovery or operator secrets are used.
"""

import json
import os
from collections import Counter
import re
from types import SimpleNamespace

import pytest

from src.cli import C4Client
from src.parts.appconfig import C4AppConfig, C4AppConfigExports
from src.parts.application_configuration_secrets import ApplicationConfigurationSecrets
from src.parts.codebuild import C4CodeBuild
from src.parts.datastore import C4Datastore
from src.parts.datastore_slim import C4DatastoreSlim
from src.parts.ecs import C4ECSApplication
from src.parts.ecs_blue_green import ECSBlueGreen
from src.parts.ecr import C4ECRExports
from src.parts.fourfront_ecs import FourfrontECSApplication
from src.parts.iam import C4IAM, C4IAMExports
from src.parts.logging import C4LoggingExports
from src.parts.network import C4Network, C4NetworkExports
from src.parts.shared_secrets import C4SharedSecretsExports
from src.parts.srce_datastore import C4SRCEDatastore
from src.parts.srce_ecs import C4SRCEECSApplication
from src.parts.srce_ecs_blue_green import SRCEECSBlueGreen
from src.parts.srce_network import C4SRCENetwork, C4SRCEDBNetwork, C4SRCEComputeNetwork
from .terraform_runner import TerraformPlans, resources

pytestmark = pytest.mark.skipif(
    os.environ.get("TF_PARITY") != "1", reason="Set TF_PARITY=1 for native mock-provider parity"
)
ACCOUNT = "123456789012"
REGION = "us-east-1"
CERT = f"arn:aws:acm:{REGION}:{ACCOUNT}:certificate/00000000-0000-0000-0000-000000000000"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/runtime"
PRIVATE = ["subnet-0aaaaaaaaaaaaaaa1", "subnet-0aaaaaaaaaaaaaaa2"]
PUBLIC = ["subnet-0aaaaaaaaaaaaaaa3", "subnet-0aaaaaaaaaaaaaaa4"]
DB_SUBNETS = ["subnet-0bbbbbbbbbbbbbbb1", "subnet-0bbbbbbbbbbbbbbb2"]
COMPUTE_SUBNETS = ["subnet-0ccccccccccccccc1", "subnet-0ccccccccccccccc2"]
NETWORK = dict(
    vpc_id="vpc-0aaaaaaaaaaaaaaa1",
    cidr_block="10.10.0.0/16",
    private_subnet_ids=PRIVATE,
    public_subnet_ids=PUBLIC,
    application_security_group_id="sg-0aaaaaaaaaaaaaaa1",
)


@pytest.fixture(scope="session")
def tf(tmp_path_factory):
    return TerraformPlans(tmp_path_factory.mktemp("native-terraform"))


def cfn_resources(template, kind):
    return [r["Properties"] for r in template["Resources"].values() if r["Type"] == kind]


def imports(kind="cgap", srce=False):
    secret_prefix = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:"
    result = {
        C4NetworkExports.VPC: NETWORK["vpc_id"],
        C4NetworkExports.APPLICATION_SECURITY_GROUP: NETWORK["application_security_group_id"],
        C4IAMExports.ECS_ASSUMED_IAM_ROLE: ROLE,
        C4ECRExports.PORTAL_REPO_URL: f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/{kind}-test",
        C4ECRExports.FALCON_SENSOR_URL: f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com/falcon-sensor",
        C4LoggingExports.APPLICATION_LOG_GROUP: "c4-logging-test",
        C4LoggingExports.APPLICATION_LOG_GROUP_BLUE: "c4-logging-test-blue",
        C4LoggingExports.APPLICATION_LOG_GROUP_GREEN: "c4-logging-test-green",
        C4AppConfigExports.EXPORT_FALCON_CID: secret_prefix + "C4AppConfigTestFalconCID-abcdef",
        C4AppConfigExports.EXPORT_FALCON_CLIENT_ID: secret_prefix + "C4AppConfigTestFalconClientID-abcdef",
        C4AppConfigExports.EXPORT_FALCON_CLIENT_SECRET: secret_prefix + "C4AppConfigTestFalconClientSecret-abcdef",
        C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS: secret_prefix + "dockerhub-abcdef",
    }
    result.update(zip(C4NetworkExports.PRIVATE_SUBNETS, PRIVATE + [f"subnet-private-{i}" for i in range(4)]))
    result.update(zip(C4NetworkExports.PUBLIC_SUBNETS, PUBLIC + [f"subnet-public-{i}" for i in range(4)]))
    return result


def resolve(value, exports=None, refs=None):
    exports, refs = exports or {}, refs or {}
    if isinstance(value, list):
        return [resolve(v, exports, refs) for v in value]
    if not isinstance(value, dict):
        return value
    if "Ref" in value:
        return {"AWS::Region": REGION, "AWS::AccountId": ACCOUNT, "WebWorkerPort": 8000, **refs}[value["Ref"]]
    if "Fn::Join" in value:
        sep, parts = value["Fn::Join"]
        return sep.join(str(resolve(p, exports, refs)) for p in parts)
    if "Fn::ImportValue" in value:
        name = value["Fn::ImportValue"]["Fn::Sub"].split("}-", 1)[1]
        return exports[name]
    return {k: resolve(v, exports, refs) for k, v in value.items()}


def lower_keys(value):
    if isinstance(value, list):
        return [lower_keys(v) for v in value]
    if isinstance(value, dict):
        return {k[0].lower() + k[1:]: lower_keys(v) for k, v in value.items()}
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@pytest.mark.parametrize("kind", ["cgap", "ff", "smaht"])
@pytest.mark.parametrize("variant", ["standalone", "blue_green", "srce", "srce-blue_green"])
@pytest.mark.parametrize("enabled", [False, True])
def test_ecs_complete_contract(tf, synthesis_config, synthesize, kind, variant, enabled):
    bg, srce = "blue_green" in variant, variant.startswith("srce")
    certificate = CERT if enabled else None
    synthesis_config(
        kind,
        "blue/green" if bg else "standalone",
        {
            "ecs.lb_certificate_arn": certificate,
            "crowdstrike.enabled": enabled,
            "vpc.id": NETWORK["vpc_id"],
            "vpc.cidr": NETWORK["cidr_block"],
            "alb.access_logs_bucket": "test-alb-logs" if enabled else None,
            "alb.access_logs_prefix": "portal" if enabled else None,
        },
    )
    cls = (
        (SRCEECSBlueGreen if bg else C4SRCEECSApplication)
        if srce
        else (ECSBlueGreen if bg else FourfrontECSApplication if kind == "ff" else C4ECSApplication)
    )
    cfn = synthesize(cls)
    ex = imports(kind, srce)
    # Standard producers expose configured six here. SRCE uses exactly its configured two.
    network = dict(NETWORK)
    if not srce:
        network.update(
            private_subnet_ids=[ex[k] for k in C4NetworkExports.PRIVATE_SUBNETS],
            public_subnet_ids=[ex[k] for k in C4NetworkExports.PUBLIC_SUBNETS],
        )
        network["cidr_block"] = C4Network.CIDR_BLOCK
    plan = tf(
        "ecs-app",
        dict(
            env_name=f"{kind}-test",
            app_kind=kind,
            srce=srce,
            deployment_paradigm="blue_green" if bg else "standalone",
            network=network,
            identities={
                "standalone": "C4AppConfigTest",
                "blue": "C4AppConfigTestBlue",
                "green": "C4AppConfigTestGreen",
            },
            log_groups={
                "standalone": "c4-logging-test",
                "blue": "c4-logging-test-blue",
                "green": "c4-logging-test-green",
            },
            ecs_role_arn=ROLE,
            portal_repository_url=ex[C4ECRExports.PORTAL_REPO_URL],
            certificate_arn=certificate,
            access_logs={"bucket": "test-alb-logs", "prefix": "portal"} if enabled else None,
            crowdstrike={
                "enabled": enabled,
                "entrypoint": ["/vendor/loader", "/application-entrypoint"],
                "sensor_image": ex[C4ECRExports.FALCON_SENSOR_URL] + ":latest",
                "cid_secret_arn": ex[C4AppConfigExports.EXPORT_FALCON_CID],
            },
        ),
    )
    # Every container/property, not task-factory sampling. Ignore resource physical IDs/tags only.
    expected_tasks = []
    for task in cfn_resources(cfn, "AWS::ECS::TaskDefinition"):
        expected_tasks.append(
            canonical(
                dict(
                    cpu=task["Cpu"],
                    memory=task["Memory"],
                    containers=lower_keys(resolve(task["ContainerDefinitions"], ex)),
                    volumes=[v["Name"] for v in task.get("Volumes", [])],
                )
            )
        )
    actual_tasks = [
        canonical(
            dict(
                cpu=r["values"]["cpu"],
                memory=r["values"]["memory"],
                containers=json.loads(r["values"]["container_definitions"]),
                volumes=[v["name"] for v in r["values"]["volume"]],
            )
        )
        for r in resources(plan, "aws_ecs_task_definition")
    ]
    assert sorted(actual_tasks) == sorted(expected_tasks)
    # Native resource counts cover the complete variant (Fourfront lacks ingester and alarms).
    for aws, native in [
        ("AWS::ECS::Cluster", "aws_ecs_cluster"),
        ("AWS::ECS::Service", "aws_ecs_service"),
        ("AWS::EC2::SecurityGroup", "aws_security_group"),
        ("AWS::ElasticLoadBalancingV2::LoadBalancer", "aws_lb"),
        ("AWS::ElasticLoadBalancingV2::TargetGroup", "aws_lb_target_group"),
        ("AWS::ElasticLoadBalancingV2::Listener", "aws_lb_listener"),
        ("AWS::CloudWatch::Alarm", "aws_cloudwatch_metric_alarm"),
    ]:
        assert len(cfn_resources(cfn, aws)) == len(resources(plan, native)), (variant, aws)
    listeners = [r["values"] for r in resources(plan, "aws_lb_listener")]
    targets = {r["values"]["arn"]: r["values"] for r in resources(plan, "aws_lb_target_group")}
    for service in resources(plan, "aws_ecs_service"):
        s = service["values"]
        assert s["network_configuration"][0]["subnets"] == sorted(network["private_subnet_ids"])
        if s["load_balancer"]:
            target = s["load_balancer"][0]["target_group_arn"]
            listener = next(item for item in listeners if item["default_action"][0].get("target_group_arn") == target)
            assert (listener["port"], listener["protocol"]) == ((443, "HTTPS") if enabled else (80, "HTTP"))
            if enabled:
                assert listener["ssl_policy"] == C4ECSApplication.LB_SSL_POLICY
                assert listener["certificate_arn"] == CERT
            assert targets[target]["health_check"][0]["path"] == "/health?format=json"
    for listener in listeners:
        action = listener["default_action"][0]
        if action["type"] == "redirect":
            assert enabled and (listener["port"], listener["protocol"]) == (80, "HTTP")
            expected = next(
                action["RedirectConfig"]
                for item in cfn_resources(cfn, "AWS::ElasticLoadBalancingV2::Listener")
                for action in item["DefaultActions"]
                if action["Type"] == "redirect"
            )
            assert {key: value for key, value in action["redirect"][0].items() if value is not None} == {
                "port": expected["Port"],
                "protocol": expected["Protocol"],
                "status_code": expected["StatusCode"],
            }
    graph = tf.graph("ecs-app")
    assert re.search(r"aws_ecs_service.this.*->.*aws_lb_listener.forward", graph), graph
    # service strategy + desired count are compared independently of generated resource names.
    cf_services = [
        canonical(
            (
                s["DesiredCount"],
                sorted((x["CapacityProvider"], x["Base"], x["Weight"]) for x in s["CapacityProviderStrategy"]),
            )
        )
        for s in cfn_resources(cfn, "AWS::ECS::Service")
    ]
    tf_services = [
        canonical(
            (
                s["values"]["desired_count"],
                sorted(
                    (x["capacity_provider"], x["base"], x["weight"]) for x in s["values"]["capacity_provider_strategy"]
                ),
            )
        )
        for s in resources(plan, "aws_ecs_service")
    ]
    assert sorted(cf_services) == sorted(tf_services)


@pytest.mark.parametrize("variant", ["standard", "srce", "slim"])
@pytest.mark.parametrize("version", [None, "14.4", "16.6", "17.6"])
@pytest.mark.parametrize("bg", [False, True])
def test_datastore_complete_contract(tf, synthesis_config, synthesize, variant, version, bg):
    synthesis_config("smaht", "blue/green" if bg else "standalone", {"rds.postgres_version": version})
    cls = {"standard": C4Datastore, "srce": C4SRCEDatastore, "slim": C4DatastoreSlim}[variant]
    cfn = synthesize(cls)
    variables = dict(
        env_name="smaht-test",
        variant=variant,
        deployment_paradigm="blue_green" if bg else "standalone",
        private_subnet_ids=DB_SUBNETS,
        db_security_group_id="sg-db",
        https_security_group_id="sg-https",
        deploying_iam_user_arn=f"arn:aws:iam::{ACCOUNT}:user/test",
        iam_s3_federator_user_arn=f"arn:aws:iam::{ACCOUNT}:user/federator",
        iam_ecs_assumed_role_arn=ROLE,
        es_volume_size=10 if variant == "slim" else 30,
    )
    if version:
        variables["rds_postgres_version"] = version
    plan = tf("datastore", variables)
    db = resources(plan, "aws_db_instance")[0]["values"]
    group = resources(plan, "aws_db_parameter_group")[0]["values"]
    cfdb = cfn_resources(cfn, "AWS::RDS::DBInstance")[0]
    cfg = cfn_resources(cfn, "AWS::RDS::DBParameterGroup")[0]
    assert db["engine_version"] == cfdb["EngineVersion"] == (version or "17.6")
    assert group["family"] == cfg["Family"] == "postgres" + db["engine_version"].split(".")[0]
    assert group["parameter"][0]["name"] == "rds.force_ssl"
    assert group["parameter"][0]["value"] == str(cfg["Parameters"]["rds.force_ssl"])
    for tfkey, cfkey in [
        ("engine", "Engine"),
        ("allocated_storage", "AllocatedStorage"),
        ("instance_class", "DBInstanceClass"),
        ("storage_type", "StorageType"),
        ("db_name", "DBName"),
        ("storage_encrypted", "StorageEncrypted"),
        ("publicly_accessible", "PubliclyAccessible"),
        ("copy_tags_to_snapshot", "CopyTagsToSnapshot"),
    ]:
        assert str(db[tfkey]) == str(cfdb[cfkey]), tfkey
    domains = cfn_resources(
        cfn, "AWS::Elasticsearch::Domain" if variant == "slim" else "AWS::OpenSearchService::Domain"
    )
    assert sorted(d["DomainName"] for d in domains) == sorted(
        d["values"]["domain_name"] for d in resources(plan, "aws_opensearch_domain")
    )
    assert len(resources(plan, "aws_s3_bucket")) == len(cfn_resources(cfn, "AWS::S3::Bucket"))
    assert len(resources(plan, "aws_sqs_queue")) == len(cfn_resources(cfn, "AWS::SQS::Queue"))
    assert len(resources(plan, "aws_kms_key")) == len(cfn_resources(cfn, "AWS::KMS::Key"))
    assert (
        resources(plan, "aws_secretsmanager_secret")[0]["values"]["name"]
        == cfn_resources(cfn, "AWS::SecretsManager::Secret")[0]["Name"]
    )
    # Source attachment metadata becomes secret JSON, with no lookup of the live version.
    secret = json.loads(resources(plan, "aws_secretsmanager_secret_version")[0]["values"]["secret_string"])
    assert secret["engine"] == db["engine"] and secret["dbname"] == db["db_name"]
    for domain in resources(plan, "aws_opensearch_domain"):
        actual = domain["values"]
        expected = next(d for d in domains if d["DomainName"] == actual["domain_name"])
        assert actual["engine_version"] == expected.get(
            "EngineVersion", "Elasticsearch_" + expected.get("ElasticsearchVersion", "")
        )
        cluster = expected.get("ClusterConfig", expected.get("ElasticsearchClusterConfig"))
        assert actual["cluster_config"][0]["instance_type"] == cluster["InstanceType"]
        assert actual["cluster_config"][0]["instance_count"] == int(cluster["InstanceCount"])
        for native, source in [
            ("ebs_enabled", "EBSEnabled"),
            ("volume_type", "VolumeType"),
            ("volume_size", "VolumeSize"),
        ]:
            assert actual["ebs_options"][0][native] == expected["EBSOptions"][source]
        assert actual["encrypt_at_rest"][0]["enabled"] == expected["EncryptionAtRestOptions"]["Enabled"]
        assert actual["node_to_node_encryption"][0]["enabled"] == expected["NodeToNodeEncryptionOptions"]["Enabled"]
        assert (
            actual["domain_endpoint_options"][0]["enforce_https"] == expected["DomainEndpointOptions"]["EnforceHTTPS"]
        )
        assert actual["vpc_options"][0]["subnet_ids"] == [DB_SUBNETS[0]]
        assert actual["vpc_options"][0]["security_group_ids"] == ["sg-https"]
    assert_bucket_queue_contract(plan, cfn)


def assert_bucket_queue_contract(plan, cfn):
    buckets = {b["BucketName"]: b for b in cfn_resources(cfn, "AWS::S3::Bucket")}
    assert set(buckets) == {r["values"]["bucket"] for r in resources(plan, "aws_s3_bucket")}
    for bucket in resources(plan, "aws_s3_bucket"):
        expected = buckets[bucket["values"]["bucket"]]
        key = bucket["address"].split("[", 1)[1]

        def satellites(kind):
            return [r["values"] for r in resources(plan, kind) if r["address"].endswith("[" + key)]

        assert (
            satellites("aws_s3_bucket_versioning")[0]["versioning_configuration"][0]["status"]
            == expected["VersioningConfiguration"]["Status"]
        )
        block = satellites("aws_s3_bucket_public_access_block")[0]
        for native, source in [
            ("block_public_acls", "BlockPublicAcls"),
            ("ignore_public_acls", "IgnorePublicAcls"),
            ("block_public_policy", "BlockPublicPolicy"),
            ("restrict_public_buckets", "RestrictPublicBuckets"),
        ]:
            assert block[native] == expected["PublicAccessBlockConfiguration"][source]
        encryption = satellites("aws_s3_bucket_server_side_encryption_configuration")
        expected_encryption = expected.get("BucketEncryption", {}).get("ServerSideEncryptionConfiguration", [])
        assert len(encryption) == len(expected_encryption)
        if encryption:
            actual_rule = encryption[0]["rule"][0]["apply_server_side_encryption_by_default"][0]
            expected_rule = expected_encryption[0]["ServerSideEncryptionByDefault"]
            assert actual_rule["sse_algorithm"] == expected_rule["SSEAlgorithm"]
            if expected_rule["SSEAlgorithm"] == "aws:kms":
                assert actual_rule["kms_master_key_id"] == resources(plan, "aws_kms_key")[0]["values"]["key_id"]
        lifecycle = satellites("aws_s3_bucket_lifecycle_configuration")
        assert bool(lifecycle) == ("LifecycleConfiguration" in expected)
        if lifecycle:
            # Rule titles are CFN logical metadata, not physical rule IDs.
            actual_rules = sorted(
                canonical(
                    (
                        r["status"],
                        r["filter"][0]["tag"][0],
                        [(t["storage_class"], t["days"]) for t in r["transition"]],
                        [(t["storage_class"], t["noncurrent_days"]) for t in r["noncurrent_version_transition"]],
                        [t["days"] for t in r["expiration"]],
                        [t["noncurrent_days"] for t in r["noncurrent_version_expiration"]],
                    )
                )
                for r in lifecycle[0]["rule"]
            )
            expected_rules = sorted(
                canonical(
                    (
                        r["Status"],
                        lower_keys(r["TagFilters"][0]),
                        [(t["StorageClass"], t["TransitionInDays"]) for t in r.get("Transitions", [])],
                        [(t["StorageClass"], t["TransitionInDays"]) for t in r.get("NoncurrentVersionTransitions", [])],
                        [r["ExpirationInDays"]] if "ExpirationInDays" in r else [],
                        (
                            [r["NoncurrentVersionExpiration"]["NoncurrentDays"]]
                            if "NoncurrentVersionExpiration" in r
                            else []
                        ),
                    )
                )
                for r in expected["LifecycleConfiguration"]["Rules"]
            )
            assert actual_rules == expected_rules
    assert sorted(
        canonical(json.loads(r["values"]["policy"])) for r in resources(plan, "aws_s3_bucket_policy")
    ) == sorted(canonical(r["PolicyDocument"]) for r in cfn_resources(cfn, "AWS::S3::BucketPolicy"))
    expected_queues = {q["QueueName"]: q for q in cfn_resources(cfn, "AWS::SQS::Queue")}
    for queue in resources(plan, "aws_sqs_queue"):
        actual = queue["values"]
        expected = expected_queues[actual["name"]]
        for native, source in [
            ("visibility_timeout_seconds", "VisibilityTimeout"),
            ("delay_seconds", "DelaySeconds"),
            ("message_retention_seconds", "MessageRetentionPeriod"),
            ("receive_wait_time_seconds", "ReceiveMessageWaitTimeSeconds"),
            ("sqs_managed_sse_enabled", "SqsManagedSseEnabled"),
        ]:
            assert actual[native] == expected[source]


def test_datastore_encryption_disabled(tf, synthesis_config, synthesize):
    synthesis_config("smaht", "standalone", {"s3.bucket.encryption": False})
    cfn = synthesize(C4Datastore)
    plan = tf(
        "datastore",
        dict(
            env_name="smaht-test",
            private_subnet_ids=DB_SUBNETS,
            db_security_group_id="sg-db",
            https_security_group_id="sg-https",
            s3_bucket_encryption=False,
            deploying_iam_user_arn=f"arn:aws:iam::{ACCOUNT}:user/test",
        ),
    )
    assert not resources(plan, "aws_kms_key")
    assert_bucket_queue_contract(plan, cfn)


def trust_statements(document):
    def many(value):
        return value if isinstance(value, list) else [value]

    # CFN emits one statement per principal; native JSON combines equivalent principals.
    return sorted(
        canonical((s["Effect"], action, key, principal, s.get("Condition")))
        for s in document["Statement"]
        for action in many(s["Action"])
        for key, values in s["Principal"].items()
        for principal in many(values)
    )


def policy_statements(statements):
    def many(value):
        return value if isinstance(value, list) else [value]

    return sorted(canonical((s["Effect"], sorted(many(s["Action"])), sorted(many(s["Resource"])))) for s in statements)


@pytest.mark.parametrize("kind", ["cgap", "ff", "smaht"])
@pytest.mark.parametrize("srce", [False, True])
@pytest.mark.parametrize("bg", [False, True])
def test_codebuild_complete_contract(tf, synthesis_config, synthesize, kind, srce, bg):
    synthesis_config(kind, "blue/green" if bg else "standalone", {"vpc.id": NETWORK["vpc_id"] if srce else None})
    cfn = synthesize(C4CodeBuild)
    ex = imports(kind, srce)
    standard = dict(
        vpc_id="vpc-standard", private_subnet_ids=["subnet-standard"], application_security_group_id="sg-standard"
    )
    selected = NETWORK if srce else standard
    plan = tf(
        "codebuild",
        dict(
            env_name=f"{kind}-test",
            app_kind=kind,
            account_id=ACCOUNT,
            deployment_paradigm="blue_green" if bg else "standalone",
            standard_network=standard,
            srce_application_network=NETWORK if srce else None,
            excluded_subnet_ids=PUBLIC + DB_SUBNETS + COMPUTE_SUBNETS,
            dockerhub_secret_arn=ex[C4SharedSecretsExports.EXPORT_DOCKERHUB_CREDENTIALS],
            falcon_secret_arns=dict(
                cid=ex[C4AppConfigExports.EXPORT_FALCON_CID],
                client_id=ex[C4AppConfigExports.EXPORT_FALCON_CLIENT_ID],
                client_secret=ex[C4AppConfigExports.EXPORT_FALCON_CLIENT_SECRET],
            ),
            github_credential_arn=f"arn:aws:codebuild:{REGION}:{ACCOUNT}:token/github",
        ),
    )
    cfprojects = {p["Name"]: p for p in cfn_resources(cfn, "AWS::CodeBuild::Project")}
    roles = {r["values"]["arn"]: r["values"] for r in resources(plan, "aws_iam_role")}
    policies = {r["values"]["role"]: json.loads(r["values"]["policy"]) for r in resources(plan, "aws_iam_role_policy")}
    assert len(cfprojects) == len(resources(plan, "aws_codebuild_project"))
    for project in resources(plan, "aws_codebuild_project"):
        p = project["values"]
        cf = cfprojects[p["name"]]
        role = roles[p["service_role"]]
        policy = policies[role["id"]]
        cfrole = cfn["Resources"][cf["ServiceRole"]["Fn::GetAtt"][0]]["Properties"]
        statements = [s for pol in cfrole["Policies"] for s in pol["PolicyDocument"]["Statement"]]
        assert policy_statements(policy["Statement"]) == policy_statements(resolve(statements, ex))
        env = p["environment"][0]
        expected_env = {
            (v["Name"], str(resolve(v["Value"], ex)), v.get("Type", "PLAINTEXT"))
            for v in cf["Environment"]["EnvironmentVariables"]
        }
        assert {(v["name"], v["value"], v["type"]) for v in env["environment_variable"]} == expected_env
        net = p["vpc_config"][0]
        assert net == dict(
            vpc_id=selected["vpc_id"],
            subnets=[selected["private_subnet_ids"][0]],
            security_group_ids=[selected["application_security_group_id"]],
        )
        assert p["source"][0]["location"] == cf["Source"]["Location"]
        assert p["source_version"] == cf["SourceVersion"]
        assert env["image"] == cf["Environment"]["Image"]
        assert env["privileged_mode"] == cf["Environment"]["PrivilegedMode"]
        allowed = next(s["Resource"] for s in policy["Statement"] if "secretsmanager:GetSecretValue" in s["Action"])
        sensor = p["name"].endswith("-pipeline-builder") and "-external-" not in p["name"]
        assert any("FalconClientSecret" in arn for arn in allowed) == sensor
    assert len(roles) == len(cfn_resources(cfn, "AWS::IAM::Role"))
    assert len(resources(plan, "aws_cloudwatch_log_group")) == len(cfn_resources(cfn, "AWS::Logs::LogGroup"))


INVENTORY = dict(
    buckets=["first-application-files", "second-application-files"],
    queues=["first-indexer-queue", "second-indexer-queue"],
    search_domains=["os-first", "es-second"],
    repositories=["first", "second", "falcon-sensor"],
    runtime_secrets=[
        "fourfront-mastertest",
        "C4AppConfigFirst",
        "C4AppConfigFirstFalconCID",
        "C4SRCEDatastoreSecondRDSSecret",
    ],
    kms_keys=["00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002"],
)


@pytest.mark.parametrize("keys", [[], INVENTORY["kms_keys"]])
def test_shared_iam_actual_attachment_graph(tf, synthesis_config, synthesize, keys):
    inventory = dict(INVENTORY, kms_keys=keys)
    snapshots = []
    for env in ["first", "second"]:
        synthesis_config(extra={"ENCODED_ENV_NAME": env, "iam.ecosystem_resources": inventory})
        cfn = synthesize(C4IAM)
        plan = tf("iam", dict(env_name=env, app_kind="cgap", ecosystem_resources=inventory))
        cf_statements = [
            s for policy in cfn_resources(cfn, "AWS::IAM::ManagedPolicy") for s in policy["PolicyDocument"]["Statement"]
        ]
        tf_statements = [
            s
            for policy in resources(plan, "aws_iam_policy")
            for s in json.loads(policy["values"]["policy"])["Statement"]
        ]
        assert policy_statements(tf_statements) == policy_statements(resolve(cf_statements))
        snapshots.append(policy_statements(tf_statements))
        assert sorted(
            trust_statements(json.loads(r["values"]["assume_role_policy"])) for r in resources(plan, "aws_iam_role")
        ) == sorted(
            trust_statements(resolve(r["AssumeRolePolicyDocument"])) for r in cfn_resources(cfn, "AWS::IAM::Role")
        )
        policies = {p["values"]["arn"]: json.loads(p["values"]["policy"]) for p in resources(plan, "aws_iam_policy")}
        attachments = [r for r in resources(plan, "aws_iam_role_policy_attachment") if r["name"] == "ecs_data"]
        assert len(attachments) == (6 if keys else 5)
        assert set(r["values"]["policy_arn"] for r in attachments) == set(policies)
        federator = resources(plan, "aws_iam_user_policy_attachment")
        assert len(federator) == (2 if keys else 1)
        for p in policies.values():
            assert len(canonical(p)) <= 6144
        # Exact-name ARN suffix matching cannot cover Falcon API credentials or same-prefix envs.
        import fnmatch

        secret_patterns = [
            a for s in tf_statements if "secretsmanager:GetSecretValue" in s["Action"] for a in s["Resource"]
        ]
        for name, allowed in [
            ("C4AppConfigFirst", True),
            ("fourfront-mastertest", True),
            ("C4AppConfigFirstOther", False),
            ("C4AppConfigFirstFalconClientSecret", False),
        ]:
            arn = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:{name}-abcdef"
            assert any(fnmatch.fnmatchcase(arn, pat) for pat in secret_patterns) == allowed
    assert snapshots[0] == snapshots[1]  # changing the current env must NEVER change shared permissions


@pytest.mark.parametrize("enabled", [False, True])
def test_flowlog_iam_deployment_contract(tf, synthesis_config, synthesize, enabled):
    synthesis_config(extra={"network.flow_logs.enabled": enabled})
    cfn = synthesize(C4Network)
    plan = tf("network", dict(flow_logs_enabled=enabled))
    assert len(resources(plan, "aws_flow_log")) == len(cfn_resources(cfn, "AWS::EC2::FlowLog")) == int(enabled)
    assert len(resources(plan, "aws_iam_role")) == len(cfn_resources(cfn, "AWS::IAM::Role")) == int(enabled)
    stack = SimpleNamespace(template=SimpleNamespace(to_dict=lambda: cfn))
    assert C4Client.build_capability_param(stack) == ("--capabilities CAPABILITY_IAM" if enabled else "")
    if enabled:
        flow = resources(plan, "aws_flow_log")[0]["values"]
        assert flow["iam_role_arn"] == resources(plan, "aws_iam_role")[0]["values"]["arn"]
        assert flow["traffic_type"] == "ALL"
        role = resources(plan, "aws_iam_role")[0]["values"]
        cfrole = cfn_resources(cfn, "AWS::IAM::Role")[0]
        assert trust_statements(json.loads(role["assume_role_policy"])) == trust_statements(
            cfrole["AssumeRolePolicyDocument"]
        )
        assert policy_statements(json.loads(role["inline_policy"][0]["policy"])["Statement"]) == policy_statements(
            cfrole["Policies"][0]["PolicyDocument"]["Statement"]
        )


@pytest.mark.parametrize("bg", [False, True])
def test_foursight_bucket_json_matches_producers(tf, synthesis_config, synthesize, monkeypatch, bg):
    synthesis_config("smaht", "blue/green" if bg else "standalone")
    monkeypatch.setattr(ApplicationConfigurationSecrets, "get_es_url", lambda: "offline:443")
    cfn = synthesize(C4AppConfig)
    plan = tf(
        "appconfig",
        dict(
            env_name="smaht-test",
            deploying_iam_user=f"arn:aws:iam::{ACCOUNT}:user/test",
            deployment_paradigm="blue_green" if bg else "standalone",
            initial_secret_overrides={"ENCODED_ES_SERVER": "offline:443"},
        ),
    )
    buckets = {b["BucketName"] for b in cfn_resources(synthesize(C4Datastore), "AWS::S3::Bucket")}
    keys = [
        "ENCODED_FILE_UPLOAD_BUCKET",
        "ENCODED_FILE_WFOUT_BUCKET",
        "ENCODED_BLOB_BUCKET",
        "ENCODED_SYSTEM_BUCKET",
        "ENCODED_METADATA_BUNDLES_BUCKET",
    ]
    cf_values = [
        json.loads(s["SecretString"])
        for s in cfn_resources(cfn, "AWS::SecretsManager::Secret")
        if s.get("SecretString", "").startswith("{")
    ]
    tf_values = [
        json.loads(s["values"]["secret_string"])
        for s in resources(plan, "aws_secretsmanager_secret_version")
        if s["name"] in ["gac", "foursight"]
    ]
    assert len(cf_values) == len(tf_values)
    for value in tf_values:
        assert value == cf_values[0]  # entire configuration contract, not only the corrected five keys
        assert all(value[k] == cf_values[0][k] and value[k] in buckets for k in keys)
        assert value["GLOBAL_ENV_BUCKET"] == cf_values[0]["GLOBAL_ENV_BUCKET"]
    # Secret content is never read and current populated versions are never reset by adoption.
    for r in resources(plan, "aws_secretsmanager_secret"):
        assert r["values"]["name"] in {s["Name"] for s in cfn_resources(cfn, "AWS::SecretsManager::Secret")}


def test_srce_three_vpc_resource_rule_contract(tf, synthesis_config, synthesize):
    synthesis_config(extra={"vpc.id": NETWORK["vpc_id"], "vpc.cidr": NETWORK["cidr_block"]})
    plan = tf(
        "srce-network",
        dict(
            application_vpc_id=NETWORK["vpc_id"],
            application_cidr=NETWORK["cidr_block"],
            application_private_subnet_ids=PRIVATE,
            application_public_subnet_ids=PUBLIC,
            db_vpc_id="vpc-0bbbbbbbbbbbbbbb1",
            db_cidr="10.20.0.0/16",
            db_subnet_ids=DB_SUBNETS,
            compute_vpc_id="vpc-0ccccccccccccccc1",
            compute_cidr="10.30.0.0/16",
            compute_subnet_ids=COMPUTE_SUBNETS,
        ),
    )
    assert not any(
        r["type"] in ["aws_vpc", "aws_subnet", "aws_route", "aws_nat_gateway", "aws_cloudtrail"]
        for r in plan["resource_changes"]
    )
    groups = {r["values"]["id"]: (r["index"], r["values"]["vpc_id"]) for r in resources(plan, "aws_security_group")}
    assert len(groups) == 7  # three Application, three Database, one retained Compute
    expected = []
    for cls, prefix in [(C4SRCENetwork, "app"), (C4SRCEDBNetwork, "db"), (C4SRCEComputeNetwork, "compute")]:
        cfn = synthesize(cls)
        for resource in cfn["Resources"].values():
            if resource["Type"] not in ["AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress"]:
                continue
            p = resource["Properties"]
            group = p["GroupId"]["Ref"]
            suffix = (
                "application"
                if group.endswith("ApplicationSecurityGroup")
                else "https" if group.endswith("HTTPSSecurityGroup") else "db"
            )
            expected.append(
                (
                    f"{prefix}_{suffix}",
                    "ingress" if resource["Type"].endswith("Ingress") else "egress",
                    p["IpProtocol"],
                    int(p["FromPort"]),
                    int(p["ToPort"]),
                    p["CidrIp"],
                )
            )
    actual = []
    for rule in resources(plan, "aws_security_group_rule"):
        if rule["name"] == "default_egress":
            continue  # explicit native preservation of EC2/CFN implicit default egress
        p = rule["values"]
        actual.append(
            (
                groups[p["security_group_id"]][0],
                p["type"],
                p["protocol"],
                p["from_port"],
                p["to_port"],
                p["cidr_blocks"][0],
            )
        )
    assert Counter(actual) == Counter(expected)


@pytest.mark.parametrize(
    "service,srce", [("higlass", False), ("jupyterhub", False), ("sentieon", False), ("sentieon", True)]
)
def test_auxiliary_ec2_contract(tf, synthesis_config, synthesize, service, srce):
    import base64
    from src.parts.higlass import C4HiglassServer
    from src.parts.jupyterhub import C4JupyterHubSupport
    from src.parts.sentieon import C4SentieonSupport
    from src.parts.srce_sentieon import C4SRCESentieonSupport
    from src.constants import EC2Constants

    synthesis_config(
        extra={
            "vpc.id": NETWORK["vpc_id"],
            "vpc.cidr": NETWORK["cidr_block"],
            "higlass.ssh_key": "synthetic-key",
            "jupyterhub.ssh_key": "synthetic-key",
            "sentieon.ssh_key": "synthetic-key",
        }
    )
    cls = {
        "higlass": C4HiglassServer,
        "jupyterhub": C4JupyterHubSupport,
        "sentieon": C4SRCESentieonSupport if srce else C4SentieonSupport,
    }[service]
    cfn = synthesize(cls)
    network = dict(NETWORK, cidr_block=NETWORK["cidr_block"] if srce else C4Network.CIDR_BLOCK)
    plan = tf(
        "ec2-service",
        dict(
            env_name="cgap-test",
            service=service,
            network=network,
            ssh_key="synthetic-key",
            compute_cidr="10.30.0.0/16" if srce else None,
        ),
    )
    instance = resources(plan, "aws_instance")[0]["values"]
    cfi = cfn_resources(cfn, "AWS::EC2::Instance")[0]
    assert instance["ami"] == cfi["ImageId"] == EC2Constants.DEFAULT_AMI_IMAGE
    assert instance["instance_type"] == cfi["InstanceType"]
    assert instance["associate_public_ip_address"] == cfi["NetworkInterfaces"][0]["AssociatePublicIpAddress"]
    assert instance["subnet_id"] == (PUBLIC[0] if service == "sentieon" else PRIVATE[0])
    if service != "sentieon":
        assert base64.b64decode(instance["user_data_base64"]).decode() == "".join(
            cfi["UserData"]["Fn::Base64"]["Fn::Join"][1]
        )
    rules = [
        (
            r["values"]["type"],
            r["values"]["protocol"],
            r["values"]["from_port"],
            r["values"]["to_port"],
            r["values"]["cidr_blocks"][0],
        )
        for r in resources(plan, "aws_security_group_rule")
        if r["name"] != "default_egress"
    ]
    expected = [
        (direction, p["IpProtocol"], int(p["FromPort"]), int(p["ToPort"]), p["CidrIp"])
        for direction, rtype in [
            ("ingress", "AWS::EC2::SecurityGroupIngress"),
            ("egress", "AWS::EC2::SecurityGroupEgress"),
        ]
        for p in cfn_resources(cfn, rtype)
    ]
    assert Counter(rules) == Counter(expected)
    for cf, native in [
        ("AWS::EC2::SecurityGroup", "aws_security_group"),
        ("AWS::ElasticLoadBalancingV2::LoadBalancer", "aws_lb"),
        ("AWS::ElasticLoadBalancingV2::TargetGroup", "aws_lb_target_group"),
        ("AWS::ElasticLoadBalancingV2::Listener", "aws_lb_listener"),
    ]:
        assert len(cfn_resources(cfn, cf)) == len(resources(plan, native))


@pytest.mark.parametrize(
    "bastion", [{}, {"enabled": True}, {"enabled": True, "ami": "ami-0123456789abcdef0", "ssh_key": "synthetic-key"}]
)
def test_optional_bastion_contract(tf, synthesis_config, synthesize, bastion):
    synthesis_config(extra={f"network.bastion.{key}": value for key, value in bastion.items()})
    cfn = synthesize(C4Network)
    plan = tf("network", dict(bastion=bastion))
    assert len(resources(plan, "aws_instance")) == len(cfn_resources(cfn, "AWS::EC2::Instance"))


def test_redis_and_source_credential_contract(tf, synthesis_config, synthesize):
    from src.parts.redis import C4Redis

    synthesis_config()
    cfn = synthesize(C4Redis)
    plan = tf("redis", dict(env_name="cgap-test", private_subnet_ids=PRIVATE, application_security_group_id="sg-app"))
    redis = resources(plan, "aws_elasticache_replication_group")[0]["values"]
    cf = cfn_resources(cfn, "AWS::ElastiCache::ReplicationGroup")[0]
    for native, legacy in [
        ("automatic_failover_enabled", "AutomaticFailoverEnabled"),
        ("at_rest_encryption_enabled", "AtRestEncryptionEnabled"),
        ("transit_encryption_enabled", "TransitEncryptionEnabled"),
        ("auto_minor_version_upgrade", "AutoMinorVersionUpgrade"),
        ("engine", "Engine"),
        ("engine_version", "EngineVersion"),
        ("node_type", "CacheNodeType"),
        ("num_cache_clusters", "NumCacheClusters"),
    ]:
        assert str(redis[native]).lower() == str(cf[legacy]).lower()
    credential = tf("codebuild-credentials", dict(github_token="SYNTHETIC_CREATE_ONLY"))
    assert resources(credential, "aws_codebuild_source_credential")[0]["values"]["auth_type"] == "PERSONAL_ACCESS_TOKEN"


@pytest.mark.parametrize(
    "field,bad",
    [
        ("buckets", ["first-*"]),
        ("runtime_secrets", ["C4AppConfigFirstFalconClientSecret"]),
        ("kms_keys", ["*"]),
        ("queues", []),
    ],
)
def test_native_shared_iam_inventory_fails_closed(tf, field, bad):
    with pytest.raises(AssertionError, match="exact physical names|Runtime roles"):
        tf("iam", dict(env_name="first", app_kind="cgap", ecosystem_resources=dict(INVENTORY, **{field: bad})))
