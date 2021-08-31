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

Write the buckets to be deleted onto each line of ``delete_pending_buckets.data.txt`` and then
run the ``delete_pending_buckets`` script, which will run an ``ls`` at first to give info
on what is in the bucket. Once you are satisfied, comment out the ``ls`` and enable the
``rb`` command in order to trigger the force deletion of the buckets. Be careful as once
this is triggered there is no going back - you will need to confirm each bucket by entering
input::

    cd scripts/
    ./delete_pending_buckets

Deleting the Datastore Stack
----------------------------

Once the S3 buckets have been cleared out it should be safe to delete the datastore stack. Note that this
operation will permanently delete the metadata associated with this environment, so ensure that if you want
it to persist, take and store an RDS snapshot that can be used later on to restore the DB.

Deleting the Remaining Stacks
-----------------------------

At this point, there should be no other stack dependencies and you can delete them in the reverse order
of how they were created::

    ecr
    network
    logging
    iam

Once this is done, all application components should be removed from the account aside
from logs and RDS backups. Clear out any remaining resources manually created and the
destruction process should be complete. Use the cost analyzer to track down any remaining
hidden costs.