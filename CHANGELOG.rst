===============
4dn-cloud-infra
===============

----------
Change Log
----------


1.2.0
=====

* Add ``repositories/`` to ``.gitignore``.

* Add command ``setup-tibanna``, ``setup-pipeline``, etc.
  (More detail needed here.)

* Add command ``datastore-attribute`` and ``show-datastore-attribute``.

* Updates to ``docs/deploy_new_account.rst``.

* In ``src/base.py``:

  * New function ``ini_file_get`` to retrieve values from a file
    in ini file format.

* In ``src/commands``:

  * Adjust ``find_command.py`` to use object hierarchy better.

  * Make programmatic interfaces to some of the data.


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

