==========================================
Deploying into a Secure Enclave (SRCE)
==========================================

Theory
------

A **SRCE** (Secure Research Collaborative Environment) deployment runs the CGAP/SMaHT
infrastructure inside VPCs that are **provided by an institution's IT/security team** rather than
VPCs this repository creates. This document describes a *fresh* deployment; the existing Fourfront
and CGAP deployments are unaffected by anything here. This satisfies environments where network infrastructure (VPCs,
subnets, routing, NAT, IGW) must be centrally owned and audited, and where application teams are
only permitted to create resources *inside* those pre-provisioned VPCs.

Instead of one self-created VPC, a SRCE deployment spans **three IT-provided VPCs**:

* **Application VPC** — runs the ECS portal and Foursight. Private subnets carry ECS tasks; public
  subnets, if the institution provides any, carry only the load balancer.
* **Database VPC** — runs RDS, OpenSearch, and Redis. Private subnets only.
* **Compute VPC** — runs Sentieon compute jobs and the SRCE Sentieon license server, plus, if
  introduced, JupyterHub/Higlass variants. Private subnets only.

The SRCE ``srce-network*`` stacks do **not** create VPCs, subnets, or routing. They create only the
security groups (and cross-VPC security-group rules) inside the IT-provided VPCs, and they *export*
the pre-existing VPC and subnet IDs using the same CloudFormation export names a normal ``network``
stack would. Downstream stacks (``srce-datastore``, ``srce-redis``, ``srce-ecs``, ``srce-sentieon``)
therefore import network values through the standard cross-stack reference pattern, unchanged from a
non-SRCE deployment — only the ``*NetworkStackNameParameter`` differs.

See ``src/parts/srce_network.py`` for the network shells and ``src/parts/srce_*.py`` for the SRCE
variants of each application stack.

.. warning::

   Updating an existing AppConfig stack may overwrite the entire portal and Foursight
   configuration in Secrets Manager with stale template values and break the existing portal.
   Update existing configuration values directly in Secrets Manager instead. The CLI warns
   before preparing an AppConfig update change set; this warning does not block deployment.
   Initial creation is exempt when CloudFormation confirms the stack does not exist.

Required configuration keys
----------------------------

SRCE deployments read the IT-provided network details from ``custom/config.json``. All subnet
values accept either a JSON array or a comma-separated string (e.g. ``"subnet-a1, subnet-a2"``).

Application VPC (ECS portal + Foursight):

* ``vpc.id`` — IT-provided Application VPC ID
* ``vpc.cidr`` — Application VPC CIDR block (used to scope security-group rules)
* ``public.subnets`` — public subnet IDs (load balancer). Optional: an enclave Application VPC
  that provides no public subnets deploys ``srce-sentieon`` unchanged.
* ``private.subnets`` — private subnet IDs for ECS tasks

Database VPC (RDS, OpenSearch, Redis):

* ``db.vpc.id`` — IT-provided Database VPC ID
* ``db.vpc.cidr`` — Database VPC CIDR block
* ``db.private.subnets`` — private subnet IDs. **Must** contain exactly ``subnet.pair_count``
  subnets (default 2), or set ``subnet.pair_count`` to match, because the RDS subnet group is built
  from ``subnet.pair_count`` subnet exports (see ``C4SRCEDBNetworkExports`` in
  ``src/parts/srce_network.py``).

Compute VPC (Sentieon jobs and license server; JupyterHub/Higlass if introduced):

* ``compute.vpc.id`` — IT-provided Compute VPC ID
* ``compute.vpc.cidr`` — Compute VPC CIDR block
* ``compute.private.subnets`` — private subnet IDs

Other relevant keys:

* ``rds.postgres_version`` — an explicit pin drives both the RDS engine version and the
  parameter-group family, which must agree or the stack fails to create. The SRCE datastore
  defaults to ``17.6``; the standard and Fourfront slim datastores keep their existing default,
  so nothing here upgrades an existing RDS instance.
* ``ecs.lb_certificate_arn`` — enables HTTPS (with an HTTP:80 redirect) on the standalone and
  blue/green portal ALBs, and each portal service then waits for its forwarding listener. Unset
  — the state of every existing deployment — retains the HTTP-only listener unchanged. The fixed
  Fourfront ECS stack does not read this setting at all. Verify the certificate covers the
  operator DNS names (the generated ALB DNS name itself is not covered by a custom certificate).
* ``ecs.bootstrap_closed`` (``srce-ecs-blue-green`` only) — creates the closed bootstrap stage; see
  "Closed ECS bootstrap stage" below. Unset or ``false`` is the normal stack.
* ``ecs.backend_tls_secret_arn`` / ``ecs.backend_tls`` (``srce-ecs`` and ``srce-ecs-blue-green``,
  SMaHT only) — re-encrypt the ALB-to-portal hop. On by default when the secret ARN and
  ``ecs.lb_certificate_arn`` are both set; see "Backend (ALB to portal) TLS" below.

* ``sentieon.ami_id`` — **required** to deploy ``srce-sentieon``. AMI the license server boots
  from; the hardened image is issued per account by the institution's IT/security team, so there
  is no default and nothing is discovered from the account. An unset or malformed value fails at
  ``cli provision`` time with a message naming the key, not at stack-creation time.
* ``sentieon.instance_type`` — defaults to ``t3.small``, the smallest SRCE default compatible
  with the institution-provided RHEL 9 image. Set it if the supplied AMI needs a different
  instance family.
* ``sentieon.volume_size`` — size in GiB of the license server's encrypted root volume
  (default 20).
* ``subnet.pair_count`` — number of subnet pairs the datastore expects (default 2).
* ``iam.omit_dev_role`` - ``true`` leaves the legacy human-access ``SMaHTDevRole`` (trusted by
  the account root) and its ``ECSDevUserRole`` output out of the ``iam`` stack. Nothing imports
  that export; the runtime roles, instance profile and S3 federator user are still created.
  Default ``false`` (unchanged template).
* ``rds.retention_policy`` / ``elasticsearch.retention_policy`` - set both ``DeletionPolicy`` and
  ``UpdateReplacePolicy`` on the RDS instance (``Delete``, ``Retain`` or ``Snapshot``) and on each
  OpenSearch domain (``Delete`` or ``Retain``; OpenSearch has no snapshot policy). Unset keeps
  CloudFormation's defaults: an update that replaces RDS or a domain deletes it without a snapshot.
* ``s3.retention_policy`` - ``Delete`` or ``Retain`` for both attributes of every datastore S3
  bucket and their S3 encryption key, so the files and the key that decrypts them outlive the stack.
* ``elasticsearch.private_subnet`` - which ``db.private.subnets`` entry (``A``, ``B``, ...) the
  OpenSearch domains use; default ``A``. Some Availability Zones offer no OpenSearch (or RDS)
  instance types - check with ``aws opensearch list-instance-type-details --retrieve-azs`` and
  pick a subnet in a supported zone; ``rds.az`` must likewise name a supported zone.
* ``redis.preferred_az`` - Availability Zone for the single-node ``srce-redis`` replication group,
  so ElastiCache does not place it in an unsupported zone of the Database subnet group. Default unset.
* ``codebuild.portal_source_type`` - ``GITLAB_SELF_MANAGED`` builds the portal from ``codebuild.repo_url``
  on the SRCE GitLab at ``codebuild.build_branch``. It needs, in the target account, a CodeConnections
  ``GitLabSelfManaged`` host (VPC-attached where GitLab is routable) and connection, both completed by a
  person in the console, plus a CodeBuild ``GITLAB_SELF_MANAGED``/``CODECONNECTIONS`` source credential
  naming that connection. The portal build role is then granted use of this account's connections.
  ``codebuild.portal_build_image`` overrides the portal build image (dev SRCE uses
  ``aws/codebuild/standard:8.0``). ``codebuild.github_builders: false`` leaves out the
  GitHub-sourced pipeline and Tibanna builders and the GitHub source credential, e.g. until a GitHub
  credential is supplied; it requires the GitLab portal source.
* ``codebuild.dhi_credentials_secret`` / ``codebuild.dhi_base_image`` - Docker Hardened Images build
  inputs for the portal: the Secrets Manager secret (JSON keys ``username``/``token``, dev SRCE name
  ``dhi-registry-credentials``) mapped to ``DHI_USERNAME``/``DHI_TOKEN``, and the pinned
  ``DHI_BASE_IMAGE``. The secret is created empty and populated by a person; set both keys or neither.
* ``foursight.api_source_cidrs`` - restricts the ``foursight-srce`` API to callers from these public
  CIDRs (for example an institution's VPN egress). See `Restricting the Foursight API by source
  address`_. Unset leaves the API open as before.

Deploy order
------------

Generate the stacks in dependency order below. ``iam``, ``ecr`` and ``logging`` are
ecosystem-shared stacks; this deployment consumes them as they already are, adding only the
``falcon-sensor`` ECR repository (see :doc:`crowdstrike`). The SRCE AppConfig GAC imports the upload
role ARN from ``srce-datastore``, so deploy the datastore before AppConfig. Bare ``cli provision``
writes templates only; ``--validate`` additionally contacts CloudFormation (not an offline check).
To create a change
set, add ``--upload-change-set`` and review/execute it separately before proceeding to consumers.
Child command failures now stop the CLI instead of reporting success::

    # 1. Network shells inside the three IT-provided VPCs (security groups + exports)
    cli provision srce-network            # Application VPC
    cli provision srce-network-db         # Database VPC
    cli provision srce-network-compute    # Compute VPC

    # 2. Ecosystem-shared prerequisites
    cli provision iam
    cli provision ecr
    cli provision logging

    # 3. Data stores in the Database VPC (also creates the S3 upload role)
    cli provision srce-datastore
    cli provision srce-redis

    # 4. AppConfig consumes the datastore's upload-role ARN; CodeBuild uses AppConfig
    cli provision appconfig
    cli provision codebuild              # vpc.id selects SRCE Application network imports

    # 5. Application and license server in their respective VPCs
    cli provision srce-ecs
    cli provision srce-sentieon         # needs sentieon.ami_id; SSM only, no key pair or SSH ingress

    # 6. Foursight for the SRCE deployment (uses the SRCE Application VPC)
    cli provision foursight-srce

.. note::
    ``srce-network`` has its own CloudFormation stack name (``c4-srce-network-main-stack``) distinct
    from the standard ``network`` stack (``c4-network-main-stack``). Deploying ``srce-network`` will
    **not** disturb any standard network stack in the account.

.. note::
    ``foursight-srce`` reads *literal* subnet and security-group IDs out of the deployed
    ``c4-srce-network-main-stack`` at package time (chalice cannot use ``ImportValue``), so step 1
    must be complete before step 5. If that stack is not up, ``cli provision foursight-srce`` now
    fails with an explicit error instead of silently packaging a Foursight config with no — or a
    stale — ``VpcConfig``.

Foursight Lambda networking contract
-------------------------------------

**Every Foursight Lambda in an SRCE deployment runs in the Application VPC, and only there.**

.. warning::
    Deploy Foursight for an SRCE environment with the **``foursight-srce``** target::

        cli provision foursight-srce --upload-change-set [--foursight-identity <GAC name>]

    Not ``foursight-smaht`` (or ``foursight`` / ``foursight-production`` /
    ``foursight-development``). Those are the non-SRCE stacks: they resolve their networking from
    the standard ``network`` stack, and ``--foursight-identity`` does **not** change that — it sets
    only the ``IDENTITY`` environment variable in the chalice config. The network source is bound
    per stack class (``NETWORK_EXPORTS``), so the *provision target* is what selects SRCE. There is
    no ``foursight-smaht-srce`` target.

    ``foursight-srce`` produces its own CloudFormation stack
    (``c4-foursight-srce-<env>-stack``) and runs alongside any existing ``foursight-smaht`` stack.

Foursight is packaged by chalice, not troposphere: the subnet and security-group IDs are baked as
literal strings into ``.chalice/config.json`` and applied by chalice to the ``VpcConfig`` of every
Lambda function it generates. ``C4FoursightSMAHTSRCEStack`` resolves them through
``C4SRCENetworkExports``:

* **Subnets** — the Application VPC private subnets from ``private.subnets``. These are rejected at
  package time if they overlap ``db.private.subnets`` or ``compute.private.subnets``.
* **Security group** — the ``ApplicationSecurityGroup`` published by the SRCE *Application* network
  stack, resolved by its CloudFormation **export name**
  (``c4-srce-network-main-stack-ApplicationSecurityGroup``). That is the identical string the
  ``srce-ecs`` stack resolves with ``Fn::ImportValue`` through ``NetworkStackNameParameter``, so
  Foursight and ECS agree by construction. A stack that publishes the output without an export name
  is still accepted, via that output's exact key (the template logical id, e.g.
  ``C4SRCENetworkMainApplicationSecurityGroup``).

A Foursight Lambda must **never** be given a second ENI in the Database or Compute VPC, and must
never fall back to a VPC's default security group. All three SRCE network stacks create an
``ApplicationSecurityGroup`` in their own VPC, so a loose match on the output-key pattern
``.*Network.*ApplicationSecurityGroup.*`` returns three groups from three different VPCs and
CloudFormation rejects every Lambda with ``Security Groups are required to be in the same VPC``.
Resolution is therefore anchored to the Application network stack's own name — see
``C4SRCENetworkExports.get_security_ids()`` in ``src/parts/srce_network.py`` and the regression
tests in ``tests/test_srce_foursight_vpc.py``.

Why Foursight cannot simply reuse the ECS mechanism verbatim: ``srce-ecs`` is CloudFormation, so it
resolves cross-stack values at *deploy* time with ``Fn::ImportValue``. Foursight is a chalice
application; its Lambda ``VpcConfig`` is written into ``.chalice/config.json`` as literal IDs
*before* any template exists, so it must look the values up itself. What it can — and now does —
share with ECS is the *identifier*: the same export name, rather than the template logical id, which
is a second name for the same output that a renamed or re-tokenized stack can change independently.

If ``cli provision foursight-srce`` reports that it cannot resolve the security group, the error
names both identifiers it tried and lists the ``ApplicationSecurityGroup`` export names that do
exist in the account (names only, never values) — normally enough to tell whether the Application
network stack is absent, differently named, or was deployed from an older revision.

Reaching the other two VPCs stays a *routing and security-group-rule* concern, not an attachment
concern. Foursight talks to RDS / OpenSearch / Redis over the IT-provided inter-VPC routing (peering
or transit gateway between the Application and Database VPCs), permitted by the narrowly scoped
cross-VPC rules that ``C4SRCENetwork`` and ``C4SRCEDBNetwork`` create — RDS ``5400-5499``, Redis
``6379``, and HTTPS ``443`` for OpenSearch, each scoped to the peer VPC's CIDR rather than to
``0.0.0.0/0``. If Foursight checks time out against the datastore, the fault is in that routing or
in those rules; adding a Database-VPC security group to the Lambdas is not the fix.

Restricting the Foursight API by source address
-----------------------------------------------

``foursight.api_source_cidrs`` (``foursight-srce`` only) is a list of public IPv4/IPv6 CIDRs, e.g.::

    "foursight.api_source_cidrs": ["192.0.2.10/32", "198.51.100.0/24"]

A comma-separated string works too. When set, ``cli provision foursight-srce`` gives the chalice
stages an API Gateway resource policy (``.chalice/foursight-api-policy.json``, generated and
gitignored). It allows ``execute-api:Invoke`` and explicitly denies it to any source address outside
the list, on ``execute-api:/*``: every stage, method and path. Requests from elsewhere get HTTP 403
before reaching a Lambda; Okta sign-in, Lambda code, permissions and schedules are unchanged.

* **It is deployed with the template.** Chalice embeds the policy in the API definition, so adding,
  changing or removing the setting changes the SAM-generated ``AWS::ApiGateway::Deployment``.
  CloudFormation then creates a new deployment, and both stages (``api`` and SAM's ``Stage``) serve
  it. A policy set on the API by hand is not in the template; whether a later template update keeps
  it is not guaranteed. Keep the setting in the environment's ``custom/config.json`` so every
  build carries it.
* **Validation.** The value must be non-empty. Each entry must be a valid network with no host bits
  set. ``0.0.0.0/0`` and ``::/0`` are refused, as are private, CGNAT, loopback, link-local and
  multicast ranges: ``aws:SourceIp`` sees the caller's public egress address, so those could never
  match. A stage that already names its own ``api_gateway_policy_file``, or uses a private
  endpoint, is never overwritten.
* **Copied, not linked.** If the source of the list (e.g. an IT-managed prefix list) changes,
  update the setting and reprovision.
* **Removing it.** Delete the setting and reprovision. Afterwards confirm with
  ``aws apigateway get-rest-api`` that no policy remains: CloudFormation's overwrite import is not
  shown here to clear an API-level policy.

Closed ECS bootstrap stage
--------------------------

The blue/green ALBs get their AWS DNS names only when they exist, but the names are needed before
then: to request hostnames and the ACM certificate that ``ecs.lb_certificate_arn`` takes. Setting::

    "ecs.bootstrap_closed": true

makes ``srce-ecs-blue-green`` create only the permanent resources: the ALB and container security
groups, the two internet-facing ALBs, the two target groups, the two clusters, the ten task
definitions and the four indexer-queue alarms (22 resources).

* **Nothing can connect.** The ALB security group has no ingress rule, and neither ALB has a
  listener.
* **Nothing runs.** No ECS service is created. Services are the only thing in this template that
  starts tasks: it defines no Application Auto Scaling, EventBridge or scheduler resource, and the
  alarms have no actions.
* **Task definitions are inert, not locked.** They are registered but never scheduled. Anyone with
  ``ecs:RunTask`` and ``iam:PassRole`` could still start one by hand. In particular the
  (initial-)deployment tasks must not be run until the application configuration is complete.
* **Outputs.** The two ``ECSApplicationURL…`` outputs are the bare ALB DNS names, since nothing is
  served.
* **Leaving the stage.** Remove the setting (or set it to ``false``), add ``ecs.lb_certificate_arn``,
  and update the stack. The change set should show only Add listeners and services, a Modify of the
  ALB security group's ingress (an in-place update) and the outputs. It should show no replacement
  of an ALB, target group, cluster or security group: their logical ids and ALB names do not depend
  on the setting. Check this in the change set before executing it.
* **Validation.** The value must be a boolean (``true``/``false``, any case). Anything else, for
  example ``yes`` or ``1``, is an error rather than silently producing the open stack. The shared
  blue/green class used by the other deployments ignores the setting.

Backend (ALB to portal) TLS
---------------------------

New SMaHT SRCE portal deployments encrypt both hops. Setting::

    "ecs.lb_certificate_arn": "arn:aws:acm:<region>:<account>:certificate/<id>",
    "ecs.backend_tls_secret_arn": "arn:aws:secretsmanager:<region>:<account>:secret:<name>-<suffix>"

turns backend TLS on in ``srce-ecs`` and ``srce-ecs-blue-green``, for ``app.kind`` ``smaht`` only.

**Per hop.**

#. Browser → ALB: HTTPS:443 with the ACM certificate, which the browser validates. HTTP:80 only
   returns a 301 to HTTPS and never forwards plaintext.
#. ALB → portal task: a second TLS session to nginx on **8443**. The target group is ``HTTPS``,
   its health check is ``HTTPS`` on ``/health?format=json``, and the targets are ``ip``. **The ALB
   does not validate the target's certificate** (chain, expiry or hostname), so this hop gives
   encryption in transit, not backend authentication. A healthy target says nothing about the
   backend certificate's expiry.
#. nginx → application workers: HTTP inside the task.

**What the template does when it is on.** It does this to the portal application container only;
the indexer, ingester, deployment and CrowdStrike sidecar containers are unchanged.

* It sets ``NGINX_TLS_ENABLED=true``.
* It injects ``NGINX_SSL_CERTIFICATE`` and ``NGINX_SSL_CERTIFICATE_KEY`` as ECS ``secrets``,
  selected by JSON key from the current version of the secret (``<arn>:<KEY>::``). They are never
  plain environment values. ECS reads them with the task's execution role, at task start only.
* It maps the single container port 8443. The image closes 8000 when TLS is on.

On the other resources:

* **Target groups.** Each portal target group is replaced by a new one, ``<name>Https`` (for
  example ``TargetGroupPortalHttps``), with its own logical id. A target group's protocol cannot
  change in place, and the group has a fixed physical name.
* **Wiring.** The HTTPS:443 listener and the portal service bind that group, and the service still
  waits for the forwarding listener.
* **Task security group.** It allows only tcp/8443 from the ALB security group, not from the VPC
  CIDR.
* ``WebWorkerPort`` stays declared, unused, so existing stacks and parameter overrides remain
  valid.

**Inputs.**

* **The secret.** It must already exist; the templates never create or replace it. It is a
  SecretString JSON with exactly the two keys ``NGINX_SSL_CERTIFICATE`` (leaf first, then
  intermediates, with real newlines) and ``NGINX_SSL_CERTIFICATE_KEY`` (the matching unencrypted
  PEM key).
* **The ARN.** Give the complete secret ARN, including AWS's 6-character suffix and without a
  ``:KEY::`` selector. Anything else is an error.
* **Execution role.** It needs ``secretsmanager:GetSecretValue`` on that ARN. The ``iam`` stack's
  ``ECSSecretManagerPolicy`` already grants that on ``*`` to the shared ECS role, which is both
  the task role and the execution role, so every task running as that role can read the key. With
  a customer-managed key the role also needs ``kms:Decrypt``.
* **Platform.** Fargate platform 1.4.0 or later is required for JSON-key selection. The services
  use ``LATEST``.

**Resolution.**

* **Unset, with both the secret and the certificate:** on.
* **Unset, with no secret:** the legacy render, byte-identical to before.
* **Unset, with a secret but no certificate:** an error rather than a quiet HTTP backend.
* ``"ecs.backend_tls": true``: on. A missing secret or certificate is an error.
* **Values other than true/false:** an error.
* **Non-SMaHT app kinds:** enabling backend TLS for any other app kind is an error.
* **The closed bootstrap stage:** it has no listeners, so there the secret alone selects backend
  TLS. Leaving the stage by adding the certificate then keeps the same HTTPS target groups. Decide
  on the secret before leaving the stage: changing the mode later swaps the target groups.

**Fallback and rollback.**

* ``"ecs.backend_tls": false`` is the explicit compatibility and rollback switch. The ALB → task
  hop is HTTP on ``WebWorkerPort``, while browser HTTPS and the :80 redirect stay as they are. The
  render is identical to the certificate-only stack, and the secret is ignored.
* Nothing falls back at runtime. If the certificate or key is missing or invalid, the task fails
  to start and is never served over plaintext.
* Switching modes on an existing stack swaps the target group and port in one update. The old
  group is removed as the new one is added, so it is not a zero-downtime migration. For a live
  environment, migrate with a parallel service and its own target group behind the listener, or
  schedule the update.

**Rotation.** ECS reads the secret only when a task starts. To rotate, write a new secret version,
then force a new deployment: running tasks keep their certificate files. Track the backend
certificate's expiry separately.

CrowdStrike Falcon and Splunk (FireLens) sidecars
-------------------------------------------------

The SMaHT dev SRCE deployment runs the Falcon sensor and a FireLens log router to Splunk HEC on its
portal, indexer, ingester and deployment tasks. Those task definitions were registered by hand
outside CloudFormation. ``srce-ecs`` and ``srce-ecs-blue-green`` can now render the same shapes, so a
deployment carries them in IaC and the next stack update does not drop them. Both features are off
unless configured. With them off, every template is byte-identical to before. Example values only::

    "crowdstrike.cid_secret_arn": "arn:aws:secretsmanager:us-east-1:111122223333:secret:<falcon-cid>-AbC123",
    "crowdstrike.sensor_image_digest": "sha256:<64 hex digits of the image in this account's falcon-sensor repo>",
    "crowdstrike.entrypoint": ["/tmp/CrowdStrike/rootfs/lib64/ld-linux-x86-64.so.2", "--library-path",
                               "/tmp/CrowdStrike/rootfs/lib64", "/tmp/CrowdStrike/rootfs/bin/bash",
                               "/tmp/CrowdStrike/rootfs/entrypoint-ecs.sh", "/home/nginx/smaht-portal/entrypoint.sh"],
    "splunk.enabled": true,
    "splunk.hec_host": "http-inputs.example.splunkcloud.com",
    "splunk.hec_token_secret_arn": "arn:aws:secretsmanager:us-east-1:111122223333:secret:<hec-token>-DeF456",
    "splunk.firelens_image": "<registry>/aws-for-fluent-bit@sha256:<64 hex digits>",
    "ecs.indexer.cpu": 1024, "ecs.indexer.memory": 2048,
    "ecs.ingester.cpu": 1024, "ecs.ingester.memory": 2048

**Falcon** (on when ``crowdstrike.cid_secret_arn`` is set):

* **CID source.** The CID comes from that existing secret. The ECS template declares no AppConfig
  parameter and imports nothing from AppConfig.
* **Do not set** ``crowdstrike.enabled`` **for this path.** That key only adds the Falcon credential
  stubs to the AppConfig template and selects the older AppConfig-sourced wiring. Never re-deploy a
  filled AppConfig stack to toggle Falcon.
* **Sidecar.** ``falcon-container`` is non-essential and runs as ``0:0``. Its image is this
  account's ``falcon-sensor`` ECR repository (the ``FalconSensorURL`` export), pinned by digest. Its
  entrypoint copies the sensor runtime into the shared ``crowdstrike-falcon-volume``, then exits 0.
* **Environment.** The sidecar gets ``FALCONCTL_OPT_FALCONCTL_CID`` from the secret. It gets
  ``FALCONCTL_OPT_BACKEND`` only when ``crowdstrike.backend`` is set; dev sets no backend.
* **Application container.** It mounts the volume read-only and is wrapped by
  ``crowdstrike.entrypoint``. It receives ``FALCONCTL_OPT_CID`` from the same secret and depends on
  the sidecar's ``SUCCESS``.

**Splunk** (on when ``"splunk.enabled": true``, a strict boolean):

* **Router sidecar.** ``splunk-firelens`` is essential, runs as ``0`` and reserves 128 CPU units
  and 256 MiB. It runs ``fluentbit`` with ``enable-ecs-log-metadata`` and the image's default
  parser, as in dev. As a result, multi-line tracebacks still arrive as one event per line.
* **Application log driver.** The application container switches to ``awsfirelens``, sending to
  ``<splunk.hec_host>:443`` with ``tls on``, ``tls.verify on`` and ``compress gzip``. TLS
  verification cannot be turned off.
* **Token and events.** The ``splunk_token`` comes from ``splunk.hec_token_secret_arn``. The
  sourcetype is ``ecs:<app kind>:<role>_v1``, and the application container depends on the router's
  ``START``.
* **Index.** ``splunk.event_index`` adds an explicit ``event_index``. Dev sets none, so the token's
  default index decides where events land.

**Scope and what does not change.**

* **Roles.** Sidecars go on the roles in ``ecs.observability_roles``, which defaults to
  ``["portal", "indexer", "ingester", "deployment"]``. Add ``"initial-deployment"`` to include it.
  By default the initial-deployment task is untouched, as in dev.
* **Container changes are additive.** Changes to containers only append. The portal keeps its
  backend TLS secrets, environment and single 8443 port mapping alongside the Falcon secret and
  both dependencies.
* **Only task definitions change.** The change touches task definitions only. It adds no
  parameter, output, secret, log group or other resource. The AppConfig, IAM, logging and ECR
  templates render identically.
* **The closed stage stays closed.** It keeps 22 resources, no services, no listeners and no ALB
  ingress. The rendered change is a new revision of the eight in-scope task definitions, which
  CloudFormation shows as ``Modify`` with replacement.

**Validation.** These are errors at build time:

* a secret ARN that is not a complete ARN (with its 6-character suffix);
* a digest that is not ``sha256:`` plus 64 hex digits, or a FireLens image that is not pinned by
  ``@sha256:``;
* a HEC host with a scheme, port or path;
* a non-boolean ``splunk.enabled``;
* an unknown role;
* ``splunk.enabled`` together with the older AppConfig-sourced Falcon wiring.

Inputs for a feature that is off are ignored.

**Warnings before enabling.**

* **Fargate sizing.** Each task's ``cpu``/``memory`` must be a valid Fargate pair (for example
  1024/2048), with room for the application, the sensor and FireLens's 256 MiB reservation. The
  default indexer is 256/512 and the default ingester 512/1024; dev runs both at 1024/2048. The
  blue/green indexer honours ``ecs.indexer.cpu``/``ecs.indexer.memory`` only once it carries these
  sidecars. Before that, as before, it stays at 256/512.
* **Account, region and images.**

  * **Sensor image.** It is resolved from this account's and region's ECR stack. Push the image
    there with ``scanOnPush`` on, and pin that digest.
  * **Sensor contract.** The sidecar's copy step assumes the image contains
    ``/entrypoint-ecs.sh``, ``/bin``, ``/etc``, ``/lib64`` and ``/usr``, and that it exits 0 once
    the copy is done. That was verified on the dev sensor image only. Before pinning a different
    sensor image, re-check its layout offline, for example by listing the image's files; this
    needs no task run.
  * **FireLens image.** It is referenced verbatim. A ``public.ecr.aws`` image needs outbound
    access to that registry. Otherwise mirror it into this account's ECR and pin the mirror's
    digest. The shared role's ECR pull grant covers a same-account repository.
* **Egress.** From the application VPC's private subnets the tasks must reach these through the
  institution's inspection path:

  * the HEC host on 443;
  * the CrowdStrike cloud;
  * the FireLens image registry, unless it is mirrored.

  Firewall rules can be keyed by source CIDR, so confirm the deployment's own CIDRs with IT; dev
  working is not evidence for prod.
* **Log retention.** Application logs go to Splunk only. CloudWatch no longer receives a copy, so
  retention is Splunk's. The sidecars' own logs go to the stack's existing application log group
  (per colour), with that group's retention. Dev's separate ``/ecs/falcon-sensor`` and
  ``/ecs/splunk-firelens`` groups are not used.
* **Shared execution role.** Both secrets are read by the shared ECS role. That role is both task
  role and execution role, and its existing ``secretsmanager:GetSecretValue`` grant on ``*``
  already covers them, so IAM is unchanged. It also means every task can read the HEC token, the
  CID and the backend TLS key. A customer-managed KMS key needs ``kms:Decrypt``. Narrowing the
  grant is separate IAM work.
* **Failure mode.** FireLens is essential. If it cannot start or exits, the task stops. The
  application waits for the Falcon sidecar's ``SUCCESS``, so a sensor image that fails its copy
  step keeps the task from starting.

**Rollout prerequisites.** Each is a deployment input or approval outside this repository:

#. **The CID secret and the HEC token secret.** Their owners create them in the deployment account.
   Use a deployment-specific HEC token, or a shared token with ``splunk.event_index``. Workers
   never copy either value.
#. **The sensor image.** The chosen sensor image is in this account's ``falcon-sensor`` repository,
   and its digest is recorded.
#. **The FireLens image.** It is mirrored and its digest recorded, or egress to its registry is
   confirmed.
#. **IT egress confirmation** for the deployment's private-subnet CIDRs: the HEC host on 443, the
   CrowdStrike cloud and, if not mirrored, the image registry.
#. **Config and render.** Add the keys above, keeping ``ecs.bootstrap_closed`` as it is. Render
   offline (``cli provision srce-ecs-blue-green --stdout``) and confirm that only task definitions
   differ.
#. **Change set review.** Upload with ``--no-execute-changeset``. Confirm the change set holds only
   the task definition modifications, then execute it under its own explicit approval.
#. **First runtime check.** It belongs to the gated normal-stage rollout that starts the services.
   Check that the sensor exits 0, the portal reaches ``/health``, a Falcon host appears for the
   CrowdStrike owner, and events arrive in Splunk with the expected sourcetype and index. Do not
   run a deployment or initial-deployment task as a smoke test: those tasks migrate data.

**Rollback.** Remove ``crowdstrike.cid_secret_arn`` and/or set ``splunk.enabled`` to ``false``, then
update the stack. The new revisions match the original task definitions, and the services pick them
up on their next deployment.

Sentieon license server
------------------------

``srce-sentieon`` is a stack of its own (``c4-srce-sentieon-<env>-stack``), separate from the
standard ``sentieon`` stack, which is left exactly as it is for the existing deployments. It puts
a Sentieon license server in the **Compute VPC**, on the first configured
``compute.private.subnets`` subnet, with **no public IP**. The portal in the Application VPC and
compute jobs reach it on tcp/8990 over IT-provided inter-VPC routing, permitted by rules scoped to
``vpc.cidr`` and ``compute.vpc.cidr``. Its dedicated security group has no SSH/admin ingress and
allows only the established license port inbound plus outbound HTTPS on tcp/443.

What the stack creates: the license-server security group and its rules, an IAM role and instance
profile granting only ``AmazonSSMManagedInstanceCore``, and the EC2 instance itself with an
encrypted ``gp3`` root volume. Its one output is the server's **private** IP
(``SentieonServerIP<Env>``).

``update-sentieon-security-groups`` reads that output, but its default stack name is the *standard*
``sentieon`` stack's, which an SRCE account does not have. Point it at this stack explicitly::

    update-sentieon-security-groups --sentieon-stack-name c4-srce-sentieon-<env>-stack

Note that this command changes live security groups; it is not part of ``cli provision``.

Deployment prerequisites, beyond the ordinary SRCE network keys:

* ``sentieon.ami_id`` **must be set.** There is no default: the hardened AMI is issued per account,
  and nothing is discovered from the account's own state. ``cli provision srce-sentieon`` fails
  offline, naming the key, if it is unset or malformed.
* Administration is through SSM Session Manager only. The instance has no SSH ingress, public IP,
  key-pair parameter, or ``sentieon.ssh_key`` configuration dependency.
* The stack creates explicitly named IAM resources, so it is deployed with
  ``CAPABILITY_NAMED_IAM``. The CLI adds that automatically
  (``C4Client.REQUIRES_CAPABILITY_NAMED_IAM``); an operator applying the template by hand must
  pass it.
* **The Compute VPC needs the centrally managed SSM egress path.** The instance has no public IP;
  Session Manager therefore depends on the institution's transit-gateway/firewall path reaching
  the SSM endpoints. This deployment assumes that central path provides the required reachability;
  the SRCE stacks create no endpoints, routes, NAT, or subnets. If the instance does not register
  with SSM, stop and report the missing centrally managed route or policy rather than changing
  network infrastructure here.
* Outbound HTTPS to the Sentieon license master must be routable through the institution's egress
  path; the dedicated security group permits only TCP/443 outbound.

Manual steps after the stack is up, as for any Sentieon license server
(https://support.sentieon.com/appnotes/license_server/): connect with
``aws ssm start-session --target <instance-id>``, install the license daemon under
``/opt/sentieon`` (the bootstrap creates ``/opt/sentieon/license`` and starts the SSM agent, and
does no more than that), and install the licence file Sentieon issues for this server's
instance ID.

Post-deploy: populate secrets
------------------------------

The appconfig stack creates secret *placeholders* (``PLACEHOLDER`` / stub values). After the
stacks are up, populate the real values with ``setup-remaining-secrets``, which fills in the GAC
plus — when ``crowdstrike.enabled`` is set — the Crowdstrike Falcon ``FalconCID`` /
``FalconClientID`` / ``FalconClientSecret`` plain-string secrets that the appconfig stack owns
per environment.

Provide the source values in ``custom/secrets.json`` (keys ``FalconCID``, ``FalconClientID``,
``FalconClientSecret``) and run::

    setup-remaining-secrets

See ``src/auto/setup_remaining_secrets/`` for the exact key names and behavior.
