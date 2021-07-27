=======================
About the vendor folder
=======================

Creating check_setup.json
=========================

The file ``vendor/check_setup.json`` used to get created automatically,
but now we generate it from the template ``check_setup.template.json``
in the parent directory via use of the ``resolve-foursight-checks``
command.

See the file ``docs/deploy_new_account.rst`` in the
``4dn-cloud-infra`` repository for information.


A footnote about this file
==========================

An additional function of this file, ``vendor/VENDOR.rst``,
is to make sure the ``vendor/`` folder already exists
to put other things in.
