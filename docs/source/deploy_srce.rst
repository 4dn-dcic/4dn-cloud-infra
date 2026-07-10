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
