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

`./4dn-cloud-infra -h`

## Documentation

["Cloud Infrastructure: Development & Deployment"](https://hms-dbmi.atlassian.net/wiki/spaces/FOURDNDCIC/pages/1929314305/Cloud+Infrastructure+Development+Deployment) on Confluence

## Architecture

* `src/cli.py` - Command-line interface for the `4dn-cloud-infra` script
* `src/infra.py` - CF template creation, verification, and execution, within `C4Infra`,
   and specific environment implementation in subclasses, e.g. `C4InfraTrial`.
* `src/network.py` - Network-specific CF class methods within `C4Network`, inherited by `C4Infra`.
* `src/db.py` - Database-specific CF class method within `C4DB`, inherited by `C4Infra`.
* `src/util.py` - General CF util functions, inherited by the domain-specific CF classes, e.g. `C4Network`.
