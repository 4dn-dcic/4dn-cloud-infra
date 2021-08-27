==========================
Account Teardown Procedure
==========================

This document walks through the teardown of an isolated CGAP deploy, roughly consisting of the
following steps.

* Uninstalling Tibanna
* Deleting the Foursight and ECS stacks
* Clearing out S3 buckets
* Deleting the datastore stack
* Deleting the remaining stacks

There are two distinct outcomes we desire when tearing down resources in an account. We might want
to delete everything in the account completely, or we might want to put the account in "hibernation"
mode so the data inside is preserved with minimal server costs. A "hibernation" teardown just
turns off the portal and Foursight by tearing down the stacks associated with these resources.
Additionally, sizing down the back-end services (ES and RDS) is critical for most effective cost
saving when operating in hibernation mode.

Uninstalling Tibanna
--------------------

First, we will remove the Tibanna deploy from this account. Do this by running the following command.:

     tibanna_cgap cleanup -g <env_name>

Output will stream as it deletes resources - no errors should occur. Note that the S3 buckets
for Tibanna are part of the datastore stack, so they are not cleared out at this time.

Note well: this step is optional when going into hibernation mode and has little effect on cost.

Deleting the Foursight and ECS Stacks
-------------------------------------

Navigate to the CloudFormation console and delete the Foursight and ECS stacks. This will bring
down both Foursight and the portal, and has the practical effect of "turning off" most API endpoints
without destroying the system. Sometimes an error is reported associated with the roles - you might need
to manually delete the roles from the IAM console before proceeding, or you can attempt the delete
again and persist the resources that failed to delete.

Note well: Stop at this step if you are looking to put an environment into hibernation mode.
Size down the RDS and ES resources sizes to minimize server cost when hibernating.

Clearing out S3 Buckets
-----------------------

Clear em out!