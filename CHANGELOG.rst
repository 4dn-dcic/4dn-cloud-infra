===============
4dn-cloud-infra
===============

----------
Change Log
----------

4.5.0
=====

Scoped to a **fresh SMaHT blue/green deployment into a Secure Research Collaborative Environment
(SRCE)**. Fourfront and the existing CGAP deployments are fixed: every stack they provision
synthesizes byte-identically to the previous release, apart from two additive shared prerequisites
named below. ``tests/test_fixed_stack_parity.py`` asserts that against a fingerprint of the
previous release's synthesis, for every app kind and both deployment paradigms.

SRCE (Secure Research Collaborative Environment) support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add SRCE infrastructure support for deploying into IT-provided VPCs (3-VPC architecture:
  Application, Database and Compute).

* New modules:

  * ``srce_network.py`` -- Network stacks (``C4SRCENetwork``, ``C4SRCEDBNetwork``,
    ``C4SRCEComputeNetwork``) that export IT-provided VPC/subnet IDs and create security groups
    with cross-VPC rules, so downstream stacks use the standard ``ImportValue`` pattern unchanged.
    The subnet-export resolvers fail loudly rather than resolving to an empty list.
  * ``srce_datastore.py`` -- SRCE datastore (``C4SRCEDatastore``) targeting the Database VPC;
    defaults ``IAMStackNameParameter`` to the shared ``c4-iam-main-stack``, and defaults to
    PostgreSQL 17.6 (the standard and Fourfront slim datastores keep their existing default, so
    no existing RDS instance is offered a major-version upgrade).
  * ``srce_ecs.py`` / ``srce_ecs_blue_green.py`` -- SRCE ECS variants
    (``C4SRCEECSApplication``, ``SRCEECSBlueGreen``) targeting the Application VPC with a
    config-driven VPC CIDR.
  * ``srce_sentieon.py`` -- SRCE Sentieon license server (``C4SRCESentieonSupport``) in the
    Application VPC, with cross-VPC rules for the Compute VPC and SSH restricted to
    ``sentieon.admin_cidr`` (defaulting to the VPC CIDR, never ``0.0.0.0/0``).
  * ``srce_redis.py`` -- SRCE Redis (``C4SRCERedis``) targeting the Database VPC.

* New ``config.json`` settings: ``vpc.id``, ``vpc.cidr``, ``public.subnets``, ``private.subnets``,
  ``db.vpc.id``, ``db.vpc.cidr``, ``db.private.subnets``, ``compute.vpc.id``,
  ``compute.vpc.cidr``, ``compute.private.subnets``, ``sentieon.admin_cidr``.

* Register the SRCE stacks in ``alpha_stacks.py`` (``srce-network``, ``srce-network-db``,
  ``srce-network-compute``, ``srce-datastore``, ``srce-ecs``, ``srce-ecs-blue-green``,
  ``srce-sentieon``, ``srce-redis``) and route them in ``cli.py``: SRCE network stacks are leaf
  stacks, and the SRCE consumers receive DB/Compute network parameter overrides. CodeBuild keeps
  its own stack identity but imports the SRCE Application VPC when ``vpc.id`` is set.

* Fix the ECS and blue/green stacks to reference ``self.NETWORK_EXPORTS.PRIVATE_SUBNETS`` /
  ``PUBLIC_SUBNETS`` instead of the hardcoded ``C4NetworkExports`` lists, so an SRCE stack
  references only the subnets that exist in its IT-provided VPC. Rendered output for the existing
  stacks is unchanged.

* One configured ``rds.postgres_version`` now drives both the RDS ``EngineVersion`` and the
  separately built parameter group's ``Family``, which must agree or stack creation fails.

* ``cli`` child commands (``docker run`` for validate/package/deploy) run non-interactively and a
  non-zero exit stops the orchestration instead of being reported as success.

* ``setup-remaining-secrets`` detects an SRCE deployment (via ``vpc.id``) and computes the RDS
  secret logical id from the SRCE datastore prefix.

* ``assure-global-env-bucket`` derives ``orchestrated_app`` / ``full_env_prefix`` from
  ``app.kind`` instead of hardcoding ``cgap``.

Foursight networking in SRCE (Application-VPC Lambda contract)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Add ``C4FoursightSMAHTSRCEStack`` and the ``foursight-srce`` provision target, which resolves
  through ``C4SRCENetworkExports`` and defaults its ``IDENTITY`` to the appconfig stack's
  Foursight configuration secret.

* Resolve the SRCE Foursight security group by CloudFormation **export name**
  (``c4-srce-network-main-stack-ApplicationSecurityGroup``) rather than by the template's output
  key -- the identical string ``srce-ecs`` resolves with ``Fn::ImportValue`` via
  ``NetworkStackNameParameter``, so the pre-deploy (chalice) and deploy-time (CloudFormation)
  paths agree by construction. The exact output key remains a fallback for a stack that publishes
  no export name, and the failure message names both identifiers and lists the
  ``ApplicationSecurityGroup`` export names that do exist (names only, never values). Adds
  ``ConfigManager.find_stack_exports()``, which reads the same ``DescribeStacks`` data and needs
  no additional API surface or IAM permission.

* ``C4SRCENetworkExports.get_security_ids()`` raises instead of returning an empty list, which
  ``foursight_core``'s ``if security_group_ids:`` gate silently swallowed, leaving a stale
  ``security_group_ids`` in the chalice config. ``get_subnet_ids()`` rejects Application-VPC
  subnets that also appear under ``db.private.subnets`` or ``compute.private.subnets``.

* **Required shared prerequisite** -- anchor the standard ``C4NetworkExports`` resolvers to the
  standard network stack's own logical-id prefix (``^C4Network...``), so the existing non-SRCE
  Foursight stacks (``foursight``/``foursight-smaht``/``foursight-production``/
  ``foursight-development``) do not match the new SRCE network stacks' ``C4SRCENetwork*`` exports.
  Without this, standing up the three SRCE network stacks in an account breaks Foursight packaging
  for the deployments already there: the loose ``.*Network.*`` patterns resolved security groups
  **and** private subnets spanning all three SRCE VPCs, and CloudFormation rejects every Lambda
  with ``Security Groups are required to be in the same VPC``. Legacy stack names such as
  ``c4-network-trial-alpha-stack`` still match, since every standard network stack takes its title
  token from ``C4NetworkBase``. Both resolvers additionally refuse a match spanning more than one
  CloudFormation stack, via the new ``ConfigManager.find_stack_outputs_by_stack()``; one of them,
  ``get_security_ids()``, previously could return an empty list and now raises -- an intentional,
  strictly-better failure, because an empty resolution was silently swallowed downstream.

* **Required shared prerequisite** -- give each Foursight variant a *deep* copy of the vendored
  chalice ``CONFIG_BASE``. ``dict(CONFIG_BASE, app_name=...)`` copies only the top level, so all
  variants shared one mutable ``stages`` dict that ``build_config()`` writes
  ``security_group_ids`` / ``subnet_ids`` into; adding the SRCE variant would otherwise leak
  Application-VPC networking into the non-SRCE variants packaged in the same process. No deployed
  resource changes.

* Package ``foursight-srce`` with the ``foursight_smaht`` poetry group.
  ``foursight_core.deploy.Deploy.build_config_and_package()`` picks the application library by
  matching the caller's ``args.stack`` against a hardcoded list of provision targets that knows
  only ``foursight-smaht``, so ``foursight-srce`` fell through to the ``foursight_cgap`` group and
  shipped a SMaHT ``app.py`` (which imports ``chalicelib_smaht``) on top of foursight-cgap's
  dependencies; the Lambda failed at startup with ``Runtime.ImportModuleError: Unable to import
  module 'app': No module named 'chalicelib_smaht'``. ``C4FoursightSMAHTSRCEStack.PackageDeploy``
  now presents ``stack='foursight-smaht'`` to that classifier on a local copy of the arguments,
  so exactly one application group is exported while the caller's deploy target -- and the
  CloudFormation stack name, change-set upload and error messages -- stay ``foursight-srce``.

Optional TLS listener and CrowdStrike Falcon sidecar (both off by default)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``ecs.lb_certificate_arn`` -- when set, the standalone and blue/green portal ALBs get an
  HTTPS:443 listener with a modern ``SslPolicy`` plus an HTTP:80 redirect, each portal service
  waits for its forwarding listener, and the portal URL output becomes ``https://``. Unset (the
  state of every existing deployment) keeps the plain HTTP:80 listener unchanged. The fixed
  Fourfront ECS stack does not read this setting.

* ``crowdstrike.enabled`` -- when set, every ECS task definition built by ``ecs.py`` /
  ``ecs_blue_green.py`` gains a non-essential ``falcon-container`` sidecar that prepares a shared
  ``crowdstrike-falcon-volume``; the application container mounts it read-only, is wrapped by the
  ``crowdstrike.entrypoint`` loader entrypoint (required when enabled, no default) and waits on
  the sidecar completing successfully. The sidecar reads the Falcon CID from Secrets Manager.
  Additional keys: ``crowdstrike.mount_path``, ``crowdstrike.sensor_image_tag``,
  ``crowdstrike.backend``. Off by default pending sensor-image publication, loader-entrypoint
  verification and task-memory validation -- see ``docs/source/crowdstrike.rst``. The fixed
  Fourfront ECS stack is not wired for the sidecar.

Additive changes to shared stacks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

These are the only two templates outside the SRCE stacks whose output differs from the previous
release, and both are strictly additive -- no pre-existing logical id is changed or removed:

* ``ecr`` gains a ``falcon-sensor`` repository and its ``FalconSensorURL`` export, the source of
  the CrowdStrike sidecar image.
* ``appconfig`` gains a Foursight configuration secret and its export, used as the ``IDENTITY``
  for ``foursight-srce`` so Foursight's configuration is separable from the portal's GAC. The
  Falcon credential stubs in the same stack are created only when ``crowdstrike.enabled`` is set.

Documentation and tests
~~~~~~~~~~~~~~~~~~~~~~~

* ``docs/source/deploy_srce.rst`` (deployment, configuration keys and the Foursight Application-VPC
  contract) and ``docs/source/crowdstrike.rst``; ``AGENTS.md`` records the cross-stack export
  sharp edges.
* ``tests/test_srce_foursight_vpc.py``, ``tests/test_srce_network_stack_name.py``,
  ``tests/test_crowdstrike_task_definitions.py``, ``tests/test_stack_regressions.py`` and
  ``tests/test_fixed_stack_parity.py`` (the deployment-boundary lock described above). All offline:
  no AWS API calls, no live CloudFormation validation.


4.4.0
=====

* Update some versions.
* Change to base.py to allow s3_encrypt_key.txt file to alternatively live
  directly in the custom directory rather than in the custom/aws_creds directory;
  simplifies the way I (dmichaels) want to organize my environment.


4.3.0
=====

* Implements identity swap procedure for SMaHT, including autoscaling configuration


4.2.0
=====

* Support for Python 3.12.


4.1.3
=====

* Update supported python versions (in pyproject.toml) from 3.8 thru 3.10 to 3.9 thru 3.11.


4.1.2
=====

* Update redis layer to pass encryption options (previously unsupported)


4.1.1
=====

* Update smaht codebuild to support pipelines


4.1.0
=====

* Small fixes encountered during deploy of SMaHT testing envs


4.0.1
=====

* Update foursight-cgap and magma for pipeline fixes


4.0.0
=====

* Upgrade to Python 3.10.
  Tried 3.11 but chalice is problematic with Python 3.11 (cffi package won't install and required at run-time).
* Build support for SMaHT.
* Fix remaining bugs associated with complete blue/green deploy.

3.10.0
======

* Add redis support
* Pin poetry 1.4.2


3.9.4
=====

* Update magma, foursight packages, and dcicutils
* Fix bugs in foursight "local" development configuration script
* Update docs to reflect previous changes to foursight deployment


3.9.3
=====
* Added scripts/prune_chalice_package.sh to prunne the Foursight Chalice package of
  modules which are useless in production and which take up space; we are butting
  up against the 50MB max for packages; called from the build_config_and_package
  function in the foursight-core module foursight_core/deploy.py.
* Minor fix to the update-kms-policy script (in case multiple keys defined).


3.9.2
=====

* Add ReadTheDocs support with landing page


3.9.1
=====

* Updates IAM policy for CloudFormation to include ``ListStacks`` permission as required by AWS


3.9.0
=====

* Upgrades ElasticSearch to use Opensearch
* Reduce redundant VPC components
* Add subnet expansion/configuration capability
* Expand CodeBuild stack to include more jobs


3.8.2
=====
* Removed symlink of app.py to app-cgap.py or app-fourfront.py
  from .github/workflows/main.yml; no longer needed.
* Changed poetry version from 1.1.15 to 1.2.0 in .github/workflows/main.yml;
  need for new "groups" feature in pyproject.toml which we use to import
  either but not both of foursight-cgap (chalicelib_cgap) or foursight (chalicelib_fourfront).
* Changes from branch fix-for-bool-in-config-json (PR-71); fix for bool types in custom/config.json.


3.8.1
=====

* Include rules for noncurrent objects in the S3 bucket lifecycle rules.


3.8.0
=====

* Changes related to Foursight React.
  * Moved Chalice routes from app-cgap.py and app-fourfront.py to foursight-core.
  * Unified app-cgap.py and app-fourfront.py into single app.py. This is done by changing
    foursight-cgap and foursight to package to chalicelib_cgap and chalicelib_fourfront,
    respectively; symlinking app.py to one or the other no longer required. And no
    longer need to muck with pyproject.tom to include one or the other; i.e these
    two libraries live side-by-side.
  * Changes to pyproject.toml associated with above, to pull in both foursight-cgap
    and foursight at once (no need to edit this depending on which is being provisioned).
    Also placed these in poetry dependency "groups" so only one or the other needs to actually
    be packaged (via chalice package); this is done in foursight_core.deploy.Deploy.build_config.
  * Fixed up show-foursight-url for new Foursight.


3.5.1
=====

* Up foursight-core to version 2.0.2.
* Up foursight to version 2.1.1.


3.5.0
=====

`PR #63: Add Kent's Bucket Swap Code <https://github.com/4dn-dcic/4dn-cloud-infra/pull/63>`_


3.4.2
=====

* In ``Makefile``, changes to simplify ``make build`` and only do the ``brew``
  parts if ``make build-full`` is done.

  * Split out ``brew`` parts of ``make configure``, creating a new
    ``make configure-brew`` target.

  * Only call ``make configure-brew`` in ``make configure-full``,
    not in ``make configure``.

  * Create ``make build-full`` to use ``make configure-full``,
    so that ``make build`` can just use newly simplified ``make configure``.


3.4.1
=====

* Pin ``poetry==1.1.15``


3.4.0
=====
* Spruced up Foursight UI a bit (virtually all in foursight-core but mentioning here).
  * New header/footer.
    * Different looks for Foursight-CGAP (blue header) and Foursight-Fourfront (green header).
    * More relevant info in header (login email, environment, stage).
  * New /info and /users page.
  * New /users and /users/{email} page.
  * New dropdown to change environments.
  * New logout link.
  * New specific error if login fails due to no user record for environment.
* Changes for C4-826 to IDENTITY-ize Foursight.
  * Set RDS_NAME in GAC (i.e. same as dbInstanceIdentifier in RDS secret).
  * For provistion foursight pass IDENTITY and STACK_NAME through to foursight-core/build_config_and_package
  * For provision foursight-development/production added --foursight-identity option to pass in GAC name
    thru to C4FoursightFourCGAPStack/C4FoursightFourfrontStack.build_config_and_package.
  * Added secretsmanager:GetSecretValue to .chalice/policy-{dev,prod}.json.
  * Some app-{cgap,fourfront}.py change related to Foursight UI changes.
  * Some refactoring to use same GAC content generation for provision datastore and appconfig;
    see application_configuration_secrets.py.
* Bunch of flake8 fixups.
* Up python version from ">=3.7.1,<3.8" from ">=3.7.1,<3.8".
* Up foursight-core to version 2.0.0.
* Up foursight-cgap to version 2.1.0.
* Up foursight (commentd out but) to version 2.1.0.


3.2.4
=====
* Added ``update-cors-policy`` poetry script target to S3 bucket CORS permission policy.

3.2.3
=====
* Added ``update-sentieon-security`` poetry script target to automate Sentieon compute node security group.

3.2.2
=====
* Added ``setup-remaining-secrets`` poetry script target to automate the setting up of the remaining secrets global application secrets.
* Added ``update-kms-policy`` poetry script target to automate the updating of the KMS policy for Foursight roles.

3.2.1
=====
* Added AWS Output for Sentieon server containing its IP address; for soon-to-come ``update-sentieon-security-group`` script.

3.2.0
=====
* Added ``init-custom-dir`` poetry script target to automate the creation of the local ``custom`` configuration directory
  implementation in src/auto/init_custom_dir.

2.0.1
=====

* Adds ``foursight_development`` module with app configuration and scripts for Foursight
  development-related tasks
* Adds script for configuring EC2 to utilize above module
* Documents use of module and script above
* Brings in foursight-cgap 1.6.0 with updated ``check_setup.json`` to work with this
  repo's ``resolve-foursight-checks`` command

1.4.0
=====

* Documents how to tear down an account, makes some small modifications as needed in support
* Enables the failed_metawfrs check on a schedule, which will automate restarting failed pipeline steps
* Implements S3 Lifecycle policies, applied to the Files and Wfoutput buckets (note that this does not activate the policies as that requires tagging from Foursight)
* Adds a small script and an ECR repository for the Tibanna AWSF image, pulls in an ECR compatible version
* Adjusts default Foursight deploy stage to prod


1.3.0
=====

* Improvements to commands, involving changes in ``src/commands``, ``src/base.py`` and ``pyproject.toml``:

  * New overall command ``setup-tibanna`` that does the Tibanna setup, and commands that do its individual parts:

    * ``setup-tibanna-pipeline-repo``

    * ``setup-tibanna-reference-files``

    * ``setup-tibanna-patches``

  * New decorator for wrapping commands in standard wrapper that binds config context and catches errors.

  * Add command ``datastore-attribute`` and ``show-datastore-attribute``.

  * Add ``show-health-page-url`` and ``open-health-page-url``

  * Adjust ``find_command.py`` to use object hierarchy better.

  * Make programmatic interfaces to some of the data.

* In ``pyproject.toml``:

  * Add dependency on ``awscli`` so that ``aws`` command can be depended upon in scripts.

  * Added dev dependency on ``flake8`` for code linting.

  * Add dev dependency on ``pygments`` for PyCharm.

* Since the new ``setup-tibanna-pipeline-repo`` creates ``repositories/cgap-pipeline``,
  ``repositories/`` is added to ``.gitignore`` so that repo won't get checked in.

* Improvements to ``docs/deploy_new_account.rst`` and ``docs/making_stack_changes.rst``.

* In ``src/base.py``:

  * New function ``ini_file_get`` to retrieve values from a file
    in ini file format.

  * New function ``check_environment_variable_consistency`` to make sure the info in ``custom/config.json``
    is consistent with environment variable settings.

  * New decorator ``@configured_main_command()`` to wrap a function definition in an error handler appropriate
    for a ``main`` function, as well as to make sure that a proper configuration context is established.

* In ``src/base.py`` and ``src/parts/datastore.py``:

  * Renaming some lingering situations that refer to 'tibanna logs' instead of 'tibanna output',
    but *not* included in this change is anything that would affect bucket names (already fixed in a prior patch)
    or stack output names (which for now we can live with being ``xxxTibannaLogs``).

* In ``src/commands/find_resources.py``, add some error checking for missing ``GLOBAL_ENV_BUCKET``.


1.2.0
=====

* Add script ``src/commands/fetch_file_items.py``

* Add script ``src/commands/create_demo_metawfr.py``

* Improvements to ``docs/deploy_new_account.rst``

  *

1.1.0
=====

* Reimplement various commands in an object-oriented way:

  * ``open-foursight-url``
  * ``open-portal-url``
  * ``show-foursight-url``
  * ``show-portal-url``

* Implement new commands:

  * ``show-network-attribute`` to see one or more named attributes of the network
    (e.g. ``PrivateSubnetA,PrivateSubnetB`` or ``ApplicationSecurityGroup``)

  * ``network-attribute`` to see the same as ``show-network-attribute`` with a ``--no-newline`` argument.
    The idea of the short name is to be compact for including between backquotes in a shell script, such as::

      tibanna_cgap deploy_zebra --subnets `network-attribute PrivateSubnetA` -e $ENV_NAME -r `network-attribute ApplicationSecurityGroup`

    in order to get the effect of::

      tibanna_cgap deploy_zebra --subnets subnet-0f17774efedb225b9 -e cgap-supertest -r sg-006cb1b93e2243af2

* Also add this CHANGELOG.rst and some testing for it being up-to-date.

1.0.0
=====

This version begins when we started to use this repository in production situations.


Older Versions
==============

A record of some older changes, if they were done by PR, can be found
`in GitHub <https://github.com/4dn-dcic/4dn-cloud-infra/pulls?q=is%3Apr+is%3Aclosed>`_.
To find the specific version numbers, see the ``version`` value in
the ``poetry.app`` section of ``pyproject.toml``, as in::

   [poetry.app]
   name = "4dn-cloud-infra"
   version = "0.1.2"
   ...etc.
