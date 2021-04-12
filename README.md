# 4dn-cloud-infra
Cloud Formation templates for 4dn-dcic AWS environments

## Setup

```
pyenv install 3.6.10
# Builds or rebuilds the env, version found in `.python-version`
pyenv exec python -m venv --clear infraenv
. infraenv/bin/activate
pip install --upgrade pip
pip install --upgrade poetry
poetry install
```

## Updates

```
poetry update
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

* `src/cli.py` - Command-line interface for the `4dn-cloud-infra` script
* `src/part.py` - Contains C4Part, an abstraction for building an AWS resource
* `src/stack.py` - Contains C4Stack, an abstraction for building a CloudFormation Stack
* `src/exports.py` - Contains C4Exports, an abstraction for defining export values from stacks
* `src/exceptions.py` - Exception handling for the package
* `src/info/` - Contains scripts for getting info from AWS
* `src/parts/` - Contains definitions of resources associated with each part (network, datastore etc)
* `src/stacks/` - Contains files that define the stacks (using resources from `src/parts/`)
