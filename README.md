# 4dn-cloud-infra
Cloud Formation templates for 4dn-dcic AWS environments

## Setup

```
pyenv exec python -m venv venv
. venv/bin/activate
pip install --update pip
pip install -r requirements.txt
```

## Usage

`./4dn-cloud-infra -h`

## Architecture

* `src/cli.py` - Command-line interface for the `4dn-cloud-infra` script
* `src/infra.py` - CF template creation, verification, and execution, within `C4Infra`,
   and specific environment implementation in subclasses, e.g. `C4InfraTrial`.
* `src/network.py` - Network-specific CF class methods within `C4Network`, inherited by `C4Infra`.
* `src/db.py` - Database-specific CF class method within `C4DB`, inherited by `C4Infra`.
* `src/util.py` - General CF util functions, inherited by the domain-specific CF classes, e.g. `C4Network`.
