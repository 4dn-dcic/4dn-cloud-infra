==========================================
Deploying into a Secure Enclave (SRCE)
==========================================

Theory
------

A **SRCE** (Secure Research Collaborative Environment) deployment runs the CGAP/SMaHT
infrastructure inside VPCs that are **provided by an institution's IT/security team** rather than
VPCs this repository creates. This satisfies environments where network infrastructure (VPCs,
subnets, routing, NAT, IGW) must be centrally owned and audited, and where application teams are
only permitted to create resources *inside* those pre-provisioned VPCs.

Instead of one self-created VPC, a SRCE deployment spans **three IT-provided VPCs**:

* **Application VPC** — runs the ECS portal and Foursight. Has public subnets (for the load
  balancer and the Sentieon license server) and private subnets (for the ECS tasks).
* **Database VPC** — runs RDS, OpenSearch, and Redis. Private subnets only.
* **Compute VPC** — reserved for compute workloads (Sentieon compute jobs, and, if introduced,
  JupyterHub/Higlass variants). Private subnets only.

The SRCE ``srce-network*`` stacks do **not** create VPCs, subnets, or routing. They create only the
security groups (and cross-VPC security-group rules) inside the IT-provided VPCs, and they *export*
the pre-existing VPC and subnet IDs using the same CloudFormation export names a normal ``network``
stack would. Downstream stacks (``srce-datastore``, ``srce-redis``, ``srce-ecs``, ``srce-sentieon``)
therefore import network values through the standard cross-stack reference pattern, unchanged from a
non-SRCE deployment — only the ``*NetworkStackNameParameter`` differs.

See ``src/parts/srce_network.py`` for the network shells and ``src/parts/srce_*.py`` for the SRCE
variants of each application stack.

Required configuration keys
----------------------------

SRCE deployments read the IT-provided network details from ``custom/config.json``. All subnet
values accept either a JSON array or a comma-separated string (e.g. ``"subnet-a1, subnet-a2"``).

Application VPC (ECS portal + Foursight):

* ``vpc.id`` — IT-provided Application VPC ID
* ``vpc.cidr`` — Application VPC CIDR block (used to scope security-group rules)
* ``public.subnets`` — public subnet IDs (load balancer, Sentieon license server)
* ``private.subnets`` — private subnet IDs (ECS tasks)

Database VPC (RDS, OpenSearch, Redis):

* ``db.vpc.id`` — IT-provided Database VPC ID
* ``db.vpc.cidr`` — Database VPC CIDR block
* ``db.private.subnets`` — private subnet IDs. **Must** contain exactly ``subnet.pair_count``
  subnets (default 2), or set ``subnet.pair_count`` to match, because the RDS subnet group is built
  from ``subnet.pair_count`` subnet exports (see ``C4SRCEDBNetworkExports`` in
  ``src/parts/srce_network.py``).

Compute VPC (Sentieon compute jobs; JupyterHub/Higlass if introduced):

* ``compute.vpc.id`` — IT-provided Compute VPC ID
* ``compute.vpc.cidr`` — Compute VPC CIDR block
* ``compute.private.subnets`` — private subnet IDs

Other relevant keys:

* ``sentieon.admin_cidr`` — CIDR (institutional VPN/admin range) allowed to SSH into the Sentieon
  license server. Defaults to the Application VPC CIDR; **never** ``0.0.0.0/0``.
* ``subnet.pair_count`` — number of subnet pairs the datastore expects (default 2).

Deploy order
------------

Provision the stacks in dependency order (using ``cli provision <stack> --validate`` first to sanity
check the emitted template, then without ``--validate`` to deploy)::

    # 1. Ecosystem-scoped shared secrets (DockerHub credentials, etc.)
    cli provision shared-secrets

    # 2. Network shells inside the three IT-provided VPCs (security groups + exports)
    cli provision srce-network            # Application VPC
    cli provision srce-network-db         # Database VPC
    cli provision srce-network-compute    # Compute VPC

    # 3. Ecosystem-shared stacks (IAM / ECR / logging / appconfig) as in a normal deploy
    cli provision iam
    cli provision ecr
    cli provision logging
    cli provision appconfig

    # 4. Data stores in the Database VPC
    cli provision srce-datastore
    cli provision srce-redis

    # 5. Application + license server in the Application VPC
    cli provision srce-ecs
    cli provision srce-sentieon

    # 6. Foursight for the SRCE deployment (uses the SRCE Application VPC)
    cli provision foursight-srce

.. note::
    ``srce-network`` has its own CloudFormation stack name (``c4-srce-network-main-stack``) distinct
    from the standard ``network`` stack (``c4-network-main-stack``). Deploying ``srce-network`` will
    **not** disturb any standard network stack in the account.

.. note::
    ``foursight-srce`` reads *literal* subnet and security-group IDs out of the deployed
    ``c4-srce-network-main-stack`` at package time (chalice cannot use ``ImportValue``), so step 2
    must be complete before step 6. If that stack is not up, ``cli provision foursight-srce`` now
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

Post-deploy: populate secrets
------------------------------

The appconfig and shared-secrets stacks create secret *placeholders* (``PLACEHOLDER`` / stub
values). After the stacks are up, populate the real values with ``setup-remaining-secrets``, which
fills in the GAC plus the auxiliary secrets:

* DockerHub credentials (JSON secret ``dhi-registry-credentials`` with ``username`` + ``token``),
  owned by the shared-secrets stack.
* Crowdstrike Falcon ``FalconCID`` / ``FalconClientID`` / ``FalconClientSecret`` (plain-string
  secrets), owned per-env by the appconfig stack.

Provide the source values in ``custom/secrets.json`` (keys ``DockerHubUsername``, ``DockerHubToken``,
``FalconCID``, ``FalconClientID``, ``FalconClientSecret``) and run::

    setup-remaining-secrets

See ``src/auto/setup_remaining_secrets/`` for the exact key names and behavior.
