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
                                 ``--env-name``
``"foursight_url_prefix"``                                                                                  Computed automatically once it
                                                                                                            exists. Not predictable before.
``"full_env_prefix"``            ``--full-env-prefix``                ``env_utils.full_env_prefix``
``"hotseat_envs"``               ``--hotseat-envs``                   ``env_utils.hotseat_envs``            Given as a comma-separated list.
``"indexer_env_name"``           ``--indexer-env-name``               ``env_utils.indexer_env_name``
``"is_legacy"``                                                                                             Computed automatically
                                 ``--mirror-env-name``                ``env_utils.mirror_env_name``         (always ``False``).
``"orchestrated_app"``                                                                                      Defaults to ``APP_KIND``.
                                 ``--org``
``"prd_env_name"``
``"public_url_table"``           ``--public-url-mappings``            ``env_utils.public_url_mappings``     Special syntax required.
                                 (see note)
``"stage_mirroring_enabled"``                                                                               Computed automatically.
``"stg_env_name"``
``"test_envs"``                  ``--test-envs``                       ``env_utils.test_envs``              Given as a comma-separated list.
``"webprod_pseudo_env"``                                                                                    Probably same as prd_env_name
                                                                                                            except for legacy compatibility.
=============================  ====================================  =====================================  =================================

