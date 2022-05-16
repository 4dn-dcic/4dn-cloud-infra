===================
Foursight-Fourfront
===================

4dn-cloud-infra allows you to deploy both foursight-fourfront and foursight-cgap.
Small code extensions would allow the deployment of other chalice
applications that implement foursight-core.

Deploy foursight-cgap following the usual instructions. For
foursight-fourfront, apply the following customizations to deploy:

#. In ``pyproject.toml``, comment out the ``foursight-cgap`` requirement, uncomment the ``foursight`` requirement and re-lock dependencies
#. Run ``./scripts/link_foursight_app.sh`` - this will create a symbolic link from ``app.py`` to ``app-fourfront.py``
#. Ensure ``config.json`` has values for both ``foursight.es_url`` and ``foursight.application_version_bucket``
#. Source main account (4dn-dcic) credentials and deploy: ``poetry run cli provision foursight --stage prod --upload-change-set``

Note that rerunning ``./scripts/link_foursight_app.sh`` will restore the
link from ``app.py`` to ``app-cgap.py`` and that you do not need to run
``resolve-foursight-checks`` when deploying foursight-fourfront.
