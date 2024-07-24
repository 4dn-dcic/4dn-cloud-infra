===============
4dn-cloud-infra
===============

----------
Change Log
----------

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
