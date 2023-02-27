=================
Architecture Docs
=================
How this codebase is organized, and some notes towards continued development
----------------------------------------------------------------------------

This document focuses on what you need to know to continue cloud infra development.

First, take a look at the cli help, in general, and for the `provision` command.

::
  ./4dn-cloud-infra --help
  ./4dn-cloud-infra provision --help

The cli help is configured at `src/cli.py`. See the `cli` function. Keep this up-to-date; it's the easiest way to
insure the documentation stays relevant to actually using this cloud infra tool.

There are two commands in place: provision, and info. `Info` should be refactored at some point, and should be used to
fetch account info via boto3 commands. It also can serve to publish google sheets with the resulting data. `Provision`
can be used to generate, upload, and execute cloudformation infrastructure. This doc focuses on how the `provision`
command works.

-----------------
Code Walk-through
-----------------

* config.json - .gitignore'd file that contains required configuration options, see `docs/setup.rst`.
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

---------
Foursight
---------

Foursight architecture differs from the standard stack.

As a class, `src.stack.C4FoursightCGAPStack` is used instead of the standard `src.stack.C4Stack`. This class does not
use troposphere parts, and as such does not implement a `build_template_from_parts` method. Instead, it implements the
`package` method, using functionality in the foursight-core library to generate a config file and Cloudformation sam
package. This package can then be uploaded as a Foursight-CGAP Cloudformation stack.

This difference translates to additional command-line configuration:

::
    --stage {dev,prod}  package stage. Must be one of 'prod' or 'dev'
                        (foursight only)
    --merge_template MERGE_TEMPLATE
                        Location of a YAML template to be merged into the
                        generated template (foursight only)
    --output_file OUTPUT_FILE
                        Location of a directory for output cloudformation
                        (foursight only)
    --trial             Use TRIAL creds when building the config (foursight
                        only; experimental)

-----------------------------------
Notes Towards Continued Development
-----------------------------------

1. Stack policies are described here_. Implementing these will be necessary to prevent stack replace operations on
   data stores, which would result in data loss.

.. _policies: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/protect-stack-resources.html

2. You will need to understand stack references and cross-stack references. Stack references are implemented with
   `Ref`, via `from troposphere import Ref`. Ref takes as instantiation argument any troposphere object, and acts as
   a link to that object. This is used throughout Cloudformation to build relational links. For instance, between a
   subnet and its corresponding VPC, to attach an Internet Gateway to a VPC.

   Cross-stack links are described below. There is some support for this using the `C4Exports` class, to export specific
   resources from a stack for use in other stacks. This class is implemented in `src/exports.py` and is sub-classed
   when needed for a specific `C4Part`, in `src/parts/`.

   Walk-through: https://aws.amazon.com/premiumsupport/knowledge-center/cloudformation-reference-resource/

   Best practices: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/best-practices.html#cross-stack

   ImportValue: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/intrinsic-function-reference-importvalue.html

   Outputs: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/outputs-section-structure.html
