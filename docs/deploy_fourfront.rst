===================
Deploying Fourfront
===================

Theory
------

The fourfront deployment process differs significantly from that of CGAP, where we
separate environments into isolated AWS accounts. Fourfront and associated 4DN Data
Portal resources run in what we consider the "main" account (4dn-dcic). We do not spin
up all stacks for fourfront that we would for CGAP - we assume significant existing
infrastructure and provision some new resources as needed. The following sections describe
which resources will need to be created and which are assumed to already exist. The idea
is that the ``fourfront_ecs`` stack will be a drop-in replacement for the Elastic
Beanstalk, behaving identically and performing comparably.

Resources Assumed to Exist
--------------------------

Under the above theory, we assume the following major infrastructure components are
already present and can either be inferred or passed as arguments to ECS.

* All associated S3 Buckets - these names must be wired directly into the GAC
* RDS Cluster - associated values can be taken directly from the Beanstalk configuration and input to the GAC
* ES Cluster - this resource must be re-created
* S3_ENCRYPT_KEY - a new one will be phased in when the beanstalk is spun down

Resources to be Created
-----------------------

Some leaf stacks will be created, including the ECR, Logging and IAM stacks. These stacks
will still be used to provide some inherent security to each fourfront env, namely separate
application log groups, separate ECR repositories (for deployment) and separate IAM
resources (in case one needs to be turned off for whatever reason).

A new stack called the appconfig stack must be created. This stack creates the global application
configuration to be used by fourfront.

An ECS stack is the main component to be created. This stack includes standard ECS resources
also present in the normal (CGAP) ECS code, but omits some CGAP-specific things, such as
the ingester service (which does not exist on fourfront).
