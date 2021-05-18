# 4dn-cloud-infra
Cloud Formation templates for 4dn-dcic AWS environments

## Setup

```
pyenv install 3.6.10
# Builds or rebuilds the env, version found in `.python-version`
pyenv exec python -m venv --clear venv
. venv/bin/activate
pip install --upgrade pip
pip install --upgrade poetry
poetry install
```

## Usage

Validate Legacy Configuration:
    
    make legacy

Validate Alpha Configuration:

    make alpha

To lint a template:

    cfn-lint path/to/template

To get help:

    ./4dn-cloud-infra -h


## Documentation

["Cloud Infrastructure: Development & Deployment"](https://hms-dbmi.atlassian.net/wiki/spaces/FOURDNDCIC/pages/1929314305/Cloud+Infrastructure+Development+Deployment) on Confluence

## Architecture

* `src/secrets.py` - .gitignore'd file that contains required customization options, see Customization below
* `src/cli.py` - Command-line interface for the `4dn-cloud-infra` script
* `src/part.py` - Contains C4Part, an abstraction for building an AWS resource
* `src/stack.py` - Contains C4Stack, an abstraction for building a CloudFormation Stack
* `src/exports.py` - Contains C4Exports, an abstraction for defining export values from stacks
* `src/exceptions.py` - Exception handling for the package
* `src/info/` - Contains scripts for getting info from AWS
* `src/parts/` - Contains definitions of resources associated with each part (network, datastore etc)
* `src/stacks/` - Contains files that define the stacks (using resources from `src/parts/`)

## Tibanna Setup

Each tibanna command is wrapped on execution, so the environment vars required for the tibanna cli configuration are
sourced with the command's execution. This requires a `test_creds.sh` file in `~/.aws_test/test_creds.sh` by default.

This file can look like this, with IAM creds to the correct account filled in:

```
export AWS_ACCESS_KEY_ID=<ACCESS_KEY_HERE>
export AWS_SECRET_ACCESS_KEY=<SECRET_HERE>
export AWS_DEFAULT_REGION=us-east-1
# only if you're using a forked tibanna repo
export TIBANNA_REPO_NAME=4dn-dcic/tibanna  # (default: 4dn-dcic/tibanna)
export TIBANNA_REPO_BRANCH=master  # (default: master)
# contains default usergroup being used
export TIBANNA_DEFAULT_STEP_FUNCTION_NAME=tibanna_unicorn_tibanna_unicorn_trial_02
```

To view the tibanna commands, use: `./4dn-cloud-infra tibanna --help`

To view the tibanna cli help message itself, use: `./4dn-cloud-infra tibanna help`

For more information on tibanna itself, see: https://tibanna.readthedocs.io/en/latest/


## Preparing for Deployment

In order to orchestrate, you must first write a config.json file at repo top level - use the below structure as a template. Note that you DO NOT and SHOULD NOT put AWS Keys in this file!

    {
        "deploying_iam_user": <your IAM user>,
        "rds.instance_size": "db.t3.xlarge",
        "rds.storage_size": 20,
        "rds.db_name": "ebdb",
        "rds.az": "us-east-1a",
        "elasticsearch.master_node_count": 3,  # XXX: Not enabled currently
        "elasticsearch.master_node_type": "c5.large.elasticsearch",
        "elasticsearch.data_node_count": 2,  # current prod data node configuration
        "elasticsearch.data_node_type": "c5.2xlarge.elasticsearch",
        "elasticsearch.volume_size": 20,
        "ecs.wsgi.count": 8,
        "ecs.wsgi.cpu": "256",
        "ecs.wsgi.mem": "512",
        "ecs.indexer.count": 4,
        "ecs.indexer.cpu": "256",
        "ecs.indexer.mem": "512",
        "ecs.ingester.count": 1,
        "ecs.ingester.cpu": "512",
        "ecs.ingester.mem": "1024"
    }


## Application Configuration

To configure the CGAP infrastructure (post-orchestration), you need to modify a JSON secret in AWS SecretsManager, identified by the stack prefix. The below values at a minimum must be present. These values will all have a placeholders in the generated application configuration secret. The comments below seek to guide the user on where to find each value.

    # Required props for deployment
    deploying_iam_user = "the power IAM user who is orchestrating the infrastructure"
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

## Testing the Deployment

Once the ECS Service has come online, the portal should be accessible from the URL output from the ECS Stack. At this point we are ready to start testing the portal functionality by loading a demo case. Some important caveats of the current test setup:

* Further customization is needed to run this on new environments. Full customization out of the box is still TODO.
* Bioinformatics analysis is completely mocked out (an output VCF is uploaded immediately).
* It may take a few hours for this process to run, especially if it is the first time.


Instructions for testing:

    # First load required knowledge base data
    make load-knowledge-base

    # Then perform metadata bundle submission
    make submission

    # Then, after following the "make submission" output instructions
    # queue output VCF ingestion
    make ingestion
    
