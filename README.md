# 4dn-cloud-infra
Infrastructure provisioning for 4dn-dcic AWS environments, using Cloudformation

## Setup

See `docs/setup.rst`.

## Updates

```
poetry update  # only if updates are needed, kept in poetry.lock
poetry install
```

## Usage

To make stack changes, see `docs/making_stack_changes.rst`. To create a new stack, see `docs/create_new_stack.rst`.
To deploy from scratch, see `docs/deploy_new_account.rst`.

Validate Legacy Configuration:
    
    make legacy

Validate Alpha Configuration:

    make alpha

To lint a template:

    cfn-lint path/to/template

To get help:

    poetry run cli -h

## Documentation

See `docs/`.

## Architecture

For an in-depth overview, see `docs/architecture.rst`.

* `src/secrets.py` - .gitignore'd file that contains required customization options, see `docs/setup.rst`.
* `src/cli.py` - Command-line interface for the `4dn-cloud-infra` script
* `src/constants.py` - Contains infrastructure configurable options
* `src/part.py` - Contains C4Part, an abstraction for building an AWS resource
* `src/stack.py` - Contains C4Stack, an abstraction for building a CloudFormation Stack
* `src/exports.py` - Contains C4Exports, an abstraction for defining export values from stacks
* `src/exceptions.py` - Exception handling for the package
* `src/info/` - Contains scripts for getting info from AWS
* `src/parts/` - Contains definitions of resources associated with each part (network, datastore etc)
* `src/stacks/` - Contains files that define the stacks (using resources from `src/parts/`)


## Testing the Deployment

Once the ECS Service has come online, the portal should be accessible from the URL output from the ECS Stack. At this
point we are ready to start testing the portal functionality by loading a demo case. Some important caveats of the
current test setup:

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
