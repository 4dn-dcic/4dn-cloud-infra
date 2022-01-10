Configuring env_utils
---------------------

The following options are configurable in ``dcicutils.env_utils``:

=============================  ===============================================================================
    Key                              Notes
=============================  ===============================================================================
``"dev_data_set_table"``         Dictionary mapping envnames to their preferred data set
``"dev_env_domain_suffix"``      e.g., .abc123def456ghi789.us-east-1.rds.amazonaws.com
``"foursight_url_prefix"``       A prefix string for use by foursight.
``"full_env_prefix"``            A string like "cgap-" that precedes all env names
``"hotseat_envs"``               A list of environments that are for testing with hot data
``"indexer_env_name"``           The environment name used for indexing
``"is_legacy"``                  Should be ``"true"`` if legacy effect is desired, otherwise omitted.
``"stage_mirroring_enabled"``    Should be ``"true"`` if mirroring is desired, otherwise omitted.
``"orchestrated_app"``           This allows us to tell 'cgap' from 'fourfront', in case there ever is one.
``"prd_env_name"``               The name of the prod env
``"public_url_table"``           Dictionary mapping envnames & pseudo_envnames to public urls
``"stg_env_name"``               The name of the stage env (or None)
``"test_envs"``                  A list of environments that are for testing
``"webprod_pseudo_env"``         The pseudo-env that is a token name to use in place of the prd env for shared
                                 stg/prd situations, replacing ``fourfront-webprod`` in the legacy system.
                                 (In orchestrations, this should usually be the same as the ``prd_env_name``.
                                 It may or may not need to be different if we orchestrate the legacy system.)
=============================  ===============================================================================

They can be configured as follows:

=============================  ====================================  =====================================  =================================
  Key                            assure-global-bucket-env arg          custom/config.json option              Notes
=============================  ====================================  =====================================  =================================
``"dev_data_set_table"``         ``--default-data-set`` (see note)     ``env_utils.dev_data_set``           Creates a table with one entry.
``"dev_env_domain_suffix"``      ``--dev-env-domain-suffix``           ``env_utils.dev_env_domain_suffix``
``"prd_env_name"``               ``--env-name`` (see note)             ``ENCODED_BS_ENV``                   The ``--env`` is assumed
                                                                                                            to be the prd for this ecosystem.
``"foursight_url_prefix"``       (not specifiable)                     (not configurable)                   Computed automatically once it
                                                                                                            exists. Not predictable before.
``"full_env_prefix"``            ``--full-env-prefix``                ``env_utils.full_env_prefix``
``"hotseat_envs"``               ``--hotseat-envs``                   ``env_utils.hotseat_envs``            Given as a comma-separated list.
``"indexer_env_name"``           ``--indexer-env-name``               ``env_utils.indexer_env_name``
``"is_legacy"``                  (not specifiable)                    (not configurable)                    Computed automatically
                                                                                                            as constant ``False``.
``"orchestrated_app"``                                                                                      Defaults to ``APP_KIND``.
                                 ``--org``                            ``s3.bucket.org``                     The org token used as part of
                                                                                                            S3 bucket name.
``"public_url_table"``           ``--public-url-mappings``            ``env_utils.public_url_mappings``     Special syntax required. See below.
                                 (see note)
``"stage_mirroring_enabled"``    ``--stg-mirroring-enabled``          ``env_utils.stg_mirroring_enabled``   Defaults to ``False``
                                                                                                            unless explicitly ``True``
                                                                                                            on command line or in config.
``"stg_env_name"``               ``--mirror-env-name`` (see note)     ``env_utils.mirror_env_name``         As ``--env``is assumed to be prd,
                                                                                                            its mirror is assumed to be stg.
``"test_envs"``                  ``--test-envs``                       ``env_utils.test_envs``              Given as a comma-separated list.
``"webprod_pseudo_env"``         (not specifiable)                     (not configurable)                   Probably same as prd_env_name
                                                                                                            except for legacy compatibility.
                                                                                                            Set it by hand in that rare case.
=============================  ====================================  =====================================  =================================


Specifying env_utils.xxx options in custom/config.json
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Specify config options in a ``custom/config.json`` file in the same syntax as you would use on a command line.
That means using strings, not lists or dictionaries, in the special syntaxes indicated here.


Specifying hotseat envs or test envs
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A list of hotseat or test envs can be specified on the command line of ``assure-global-bucket-env`` using
``--hotseat-envs`` or ``test-envs``, respectively, and giving a comma-separated list. For example::

    assure-global-bucket-env --test-envs acme-demotest,acme-uitest


Specifying public URL mappings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A mapping table is needed for public URL mappings.

* Mapping table entries are separated by commas.

* Each mapping table entry has one of two forms:

  * ``<env_name>=<host>``

  * ``<special_public_env_name>=<internal_env_name>=<host>``

  The host can be a simple host name (``cgap.foo.com``) or a spec
like ``http://cgap.foo.com`` or ``https://cgap.foo.com``. Note that
if you want to override the ``https://`` default for connections,
specifying ``http://...`` is the intended and only way to do that.

For example:

    assure-global-bucket-env --public-url-mappings devtest=cgap-devtest=cgap-devtest.hms.harvard.edu

means the same as just the following::

    assure-global-bucket-env --public-url-mappings devtest=cgap-devtest=cgap-devtest.hms.harvard.edu

*if* the ``custom/config.json`` contains::

    "env_utils.public_url_mappings": "devtest=cgap-devtest=cgap-devtest.hms.harvard.edu",

Either of these would install something in the bucket envs definition that looked like::

    {
      ...,
      "public_url_table": [
        {
          "name": "devtest",
          "url": "https://cgap-devtest.hms.harvard.edu",
          "host": "cgap-devtest.hms.harvard.edu",
          "environment": "cgap-devtest"
        },
      ...
    ]

