=================
Architecture Docs
=================
How this codebase is organized, and some notes towards continued development
----------------------------------------------------------------------------


---------
Foursight
---------

Foursight architecture differs from the standard stack.

As a class, `src.stack.C4FoursightCGAPStack` is used instead of the standard `src.stack.C4Stack`. This class does not
use troposphere parts, and as such does not implement a `build_template_from_parts` method. Instead, it implements the
`package` method, using functionality in the foursight-core library to generate a config file and Cloudformation sam
package. This package can then be uploaded as a Foursight-CGAP Cloudformation stack.

This difference translates to additional command-line configuration.
