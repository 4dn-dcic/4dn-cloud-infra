=====
Setup
=====
Setting up the 4dn-cloud-infra repo
-----------------------------------

------------
Installation
------------

First, make sure pyenv_ is installed and configured. Then, create the virtual environment for this repo, and install
dependencies via poetry_.

.. _pyenv: https://github.com/pyenv/pyenv
.. _poetry: https://python-poetry.org/

For example::

    pyenv install 3.7.12
    pyenv virtualenv 3.7.12 4dn-cloud-infra37
    make build

For more details on the build commands, see the ``Makefile``.

----------------------
Access To Test Account
----------------------

4dn-cloud-infra mounts credentials found in ``custom/aws_creds`` to the ``awscli`` Docker
container where the actual CloudFormation templates are built.

Set up a credentials file::

    [default]
    aws_access_key_id = XXX
    aws_secret_access_key = XXX

a config file::

    [default]
    region = us-east-1

and a test_creds.sh file::

    # Personal AWS keys
    export AWS_ACCESS_KEY_ID=`grep "aws_access_key_id" ~/.aws/credentials | sed -e 's/.* = //'`
    export AWS_SECRET_ACCESS_KEY=`grep "aws_secret_access_key" ~/.aws/credentials | sed -e 's/.* = //'`
    export AWS_SESSION_TOKEN=`grep "aws_session_token" ~/.aws/credentials | sed -e 's/.* = //'`
    export AWS_DEFAULT_REGION=`grep "region" ~/.aws/config | sed -e 's/.* = //'`

    # app config
    export GLOBAL_BUCKET_ENV=<bucket>
    export GLOBAL_ENV_BUCKET=<bucket>
    export S3_ENCRYPT_KEY=<key>
    export S3_ENCRYPT_KEY_ID=<key_id>

    # auth0 for foursight
    export CLIENT_ID=<Auth0ClientID>
    export CLIENT_SECRET=<Auth0Secret>

    # tibanna config
    export TIBANNA_VERSION=x.x.x
    export ACCOUNT_NUMBER=<number>


**Note**: The credentials and config file **must** contain the ``[default]`` profile
for full functionality. Beware of copying Okta's profile name into these files,
especially the credentials file.

-------------
Configuration
-------------

After things are installed, you'll need to fill out config info. In order to orchestrate, you must first write a
config.json file at repo top level - use the JSON structure below as a template.

* You'll need to remove the comments because, unlike Python, `.json` dictionary files have no comment syntax.
* Note that you DO NOT and SHOULD NOT put AWS Keys in this file!
* Some of the values it wants won't be known until after deploying ``datastore``, so don't worry about that.

The format is JSON, though remember that JSON files, unlike Python files, cannot have comments and cannot have
a trailing comma inside a list or dictionary::

    {
        "deploying_iam_user": <your IAM user name, not the full ARN>,
        "account_number": <your account number, found in the console>,
        "identity": <name of AWS Secret containing application configuration>,
        "ENCODED_BS_ENV": <the-environment-you-want>,
        "GLOBAL_ENV_BUCKET": <name of the global env bucket>,
        "GLOBAL_BUCKET_ENV": <same as GLOBAL_ENV_BUCKET, but for backward compatibility>,
        "s3.bucket.org": <a short name meant to uniquely identify your organization>,

        "ecs.indexer.count": 4,
        "ecs.indexer.cpu": "256",
        "ecs.indexer.mem": "512",
        "ecs.ingester.count": 1,
        "ecs.ingester.cpu": "512",
        "ecs.ingester.mem": "1024",
        "ecs.wsgi.count": 2,
        "ecs.wsgi.cpu": "4096",
        "ecs.wsgi.mem": "8192",
        "elasticsearch.data_node_count": 1,
        "elasticsearch.data_node_type": "c5.xlarge.elasticsearch",
        "elasticsearch.master_node_count": 3,  # XXX: Not enabled currently
        "elasticsearch.master_node_type": "c5.large.elasticsearch",
        "elasticsearch.volume_size": 20,
        "rds.az": "us-east-1a",
        "rds.db_name": "ebdb",
        "rds.db_port": "5432",
        "rds.instance_size": "db.t3.large",
        "rds.storage_size": 20
    }

To configure the CGAP infrastructure (post-orchestration), you need to modify a JSON secret in AWS SecretsManager,
identified by the stack prefix. At minimum, the values below must be present. These values will all have a placeholders
in the generated application configuration secret. Some values need to be retrieved from the administrator configuring
the system. Note that Auth0 configuration is NOT part of the setup at this time - it assumes an existing Auth0
application and that the orchestrating user has access. Comments seek to guide the user on where to find each value::

    # Required props for deployment
    deploying_iam_user = "the power IAM user who is orchestrating the infrastructure (may soon not be needed)"
    Auth0Client = "Get from Auth0"
    Auth0Secret = "Get from Auth0"
    ENV_NAME = "desired env_name, for example: cgap-mastertest"
    ENCODED_BS_ENV = "same as above"
    ENCODED_DATA_SET = "specifies load_data behavior: one of 'prod', 'test'"
    ENCODED_ES_SERVER = "Get output from datastore stack, include port 443"
    ENCODED_VERSION = "Should get picked up from application version"
    ENCODED_FILES_BUCKET = Get output from datastore stack, for example application-cgap-mastertest-files
    ENCODED_WFOUT_BUCKET = name_of_wfout_bucket, for example application-cgap-mastertest-wfout
    ENCODED_BLOBS_BUCKET = name_of_blobs_bucket, for example application-cgap-mastertest-blobs,
    ENCODED_SYSTEM_BUCKET = name_of_system_bucket, for example application-cgap-mastertest-system
    ENCODED_METADATA_BUNDLE_BUCKET = name_of_metadata_bundle_bucket, for example application-cgap-mastertest-metadata-bundles
    LANG = "en_US.UTF-8"
    LC_ALL = "en_US.UTF-8"
    RDS_HOSTNAME = "Get from RDS Secret"
    RDS_DB_NAME = "Get from RDS Secret"
    RDS_PORT = "Get from RDS Secret"
    RDS_USERNAME = "Get from RDS Secrete"
    RDS_PASSWORD = "Get from RDS Secret"
    S3_ENCRYPT_KEY = "generated by Cloudformation in KMS"
    SENTRY_DSN = "add if you want Sentry"
    reCaptchaSecret = "for reCaptcha in production"

-------------
Tibanna Setup
-------------

To deploy tibanna, do so from ``tibanna_ff``. Note that ``GLOBAL_BUCKET_ENV`` must be set along
with all other vars from ``test_creds.sh``. Deploy like so::

    tibanna_cgap deploy_zebra --subnets <subnet> -e <env> -r <security_group>

To clean up (uninstall) tibanna from the account, run::

    tibanna_cgap cleanup -g <env>

For more information on tibanna itself, see: https://tibanna.readthedocs.io/en/latest/
