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

---------
Foursight
---------

Foursight architecture differs from the standard stack.

As a class, `src.stack.C4FoursightCGAPStack` is used instead of the standard `src.stack.C4Stack`. This class does not
use troposphere parts, and as such does not implement a `build_template_from_parts` method. Instead, it implements the
`package` method, using functionality in the foursight-core library to generate a config file and Cloudformation sam
package. This package can then be uploaded as a Foursight-CGAP Cloudformation stack.

This difference translates to additional command-line configuration.
