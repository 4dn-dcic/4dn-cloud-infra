===========
Deploy Docs
===========
Provisioning A C4 Cloud Infra Account From Scratch
--------------------------------------------------

This doc walks one through provisioning a c4 cloud infra account from scratch. If you already have configured your c4
cloud infra setup, and created an account with a basic IAM user provisioning, skip to Step Two.

Step Zero: Fill in Config
-------------------------

To be documented.

Step One: Create New Account
----------------------------

1. If there's a base account to be used, for billing or administrative purposes, go to that account's `Organizations
   service <https://console.aws.amazon.com/organizations/home?#/accounts>`_. Then, add an account.

   Otherwise, create a new account from scratch, with billing information and contact information, from the `AWS login
   page <https://aws.amazon.com/>`_.

2. Create one new IAM user separate from the root account login, to be used to provision the rest of the account's
   resources. More information on this bootstrap step to be documented. As a result of this step, you should have this
   account's credentials in a configurable `.aws` directory, by default, `.aws_test/credentials`.


Step Two: CGAP Orchestration with Cloud Formation
-------------------------------------------------

1. Upload base templates required for starting the application.

::

    ./4dn-cloud-infra provision iam --validate --alpha --upload_change_set
    ./4dn-cloud-infra provision logging --validate --alpha --upload_change_set
    ./4dn-cloud-infra provision network --validate --alpha --upload_change_set
    ./4dn-cloud-infra provision ecr --validate --alpha --upload_change_set
    ./4dn-cloud-infra provision datastore --validate --alpha --upload_change_set

These will take about fifteen minutes or so to finish provisioning, and should be run in order. While they are
instantiating, write application configuration in secrets manager -- more documentation on this to follow.

Once your new ECR comes online, upload application images to it. See the cgap-portal Makefile:
`src/deploy/docker/production/Makefile`. Note that these image tags are required: "latest", "latest-indexer",
"latest-ingester", "latest-deployment".

2. Once all base stacks have finishing instantiating -- all stacks should be in state `UPDATE_COMPLETE` -- you can
   provision the application stack.

   ::

     ./4dn-cloud-infra provision ecs --validate --alpha --upload_change_set

3. Once the application has finishing instantiating, you can deploy the portal.

To do this in the console, navigate to the ECS Console and locate the Deployment Service. Invoke this task in the newly
created VPC and private subnets. Attach the Application and DB security groups. (An automated deploy script to follow.)

With this done, once the deployment container is online, logs will immediately stream to the task, and Cloudwatch.


Step Three: Finalizing CGAP Configuration
-----------------------------------------

At this point, the application and its required resources have come online. Here, we upload env configuration to enable
foursight checks on the application.

As part of the datastore provisioning, your new S3 buckets are online. There's a global application S3 bucket, as
referenced in C4DatastoreExports.FOURSIGHT_APPLICATION_VERSION_BUCKET. The name of your C4 deployment's global
application bucket can be found on the 'Outputs' tab of your datastore CloudFormation stack.

Upload a global env configuration to enable foursight. Automated upload script to follow. For example:

::

  { "fourfront": "http://fourfront-cgapdev.eba-78e5hhvz.us-east-1.elasticbeanstalk.com/",
    "es": "https://vpc-c4datastoretriales-nm4mam24al26aalf5o3dxervde.us-east-1.es.amazonaws.com/",
    "ff_env": "fourfront-cgap-mastertest"
  }

