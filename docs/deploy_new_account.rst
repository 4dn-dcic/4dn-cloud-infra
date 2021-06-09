=======================
Deploying a New Account
=======================
Provisioning A C4 Cloud Infra Account From Scratch
--------------------------------------------------

This doc walks one through provisioning a c4 cloud infra account from scratch. If you already have configured your c4
cloud infra setup, and created an account with a basic IAM user provisioning, skip to Step Two.

Step Zero: Setup: Installation, and fill in config
--------------------------------------------------

First, see `doc/setup.rst` for detailed setup instructions.

Step One: Create New Account
----------------------------

1. If there's a base account to be used, for billing or administrative purposes, go to that account's `Organizations
   service <https://console.aws.amazon.com/organizations/home?#/accounts>`_. Then, add an account.

   Otherwise, create a new account from scratch, with billing information and contact information, from the `AWS login
   page <https://aws.amazon.com/>`_.

Note that the HMS email you use to create this account is treated as the 'root account' login.

2. Once the account is created, you can request a password reset for a 'root account' login (not IAM login). When this
   is done, you'll be able to log into your new account with this password.

   The root account should not be used for routine use; an IAM user should be used for routine purposes.

3. Create one new IAM user separate from the root account login, to be used to provision the rest of the account's
   resources. More information on this bootstrap step to be documented. As a result of this step, you should have this
   account's credentials in a configurable `.aws` directory, by default, `.aws_test/credentials`.


Step Two: CGAP Orchestration with Cloud Formation
-------------------------------------------------

Note: you will need to request more elastic IPs from AWS, as described here_.

: _here https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html

You can request this from the 'Service Quotas' console_.

: _console https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas

1. Upload base templates required for starting the application.

::

    poetry run cli provision iam --validate --alpha --upload_change_set
    poetry run cli provision logging --validate --alpha --upload_change_set
    poetry run cli provision network --validate --alpha --upload_change_set
    poetry run cli provision ecr --validate --alpha --upload_change_set
    poetry run cli provision datastore --validate --alpha --upload_change_set

These will take about fifteen minutes or so to finish provisioning, and should be run in order. While they are
instantiating, write application configuration in secrets manager -- more documentation on this to follow.

Once your new ECR comes online, upload application images to it. See the cgap-portal Makefile:
`src/deploy/docker/production/Makefile`. Note that these image tags are required: "latest", "latest-indexer",
"latest-ingester", "latest-deployment".

2. Once all base stacks have finishing instantiating -- all stacks should be in state `UPDATE_COMPLETE` -- you can
   provision the application stack.

   ::

     poetry run cli provision ecs --validate --alpha --upload_change_set

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

Upload a global env configuration to enable foursight. Automated upload script to follow. TODO.

Currently, you can upload the file `.chalice/cgap-mastertest` to the global bucket env, which, on the trial account, is
`s3://foursight-cgap-mastertest-envs/cgap-mastertest`.

To deploy foursight, use this command:

::
    source ~/.aws_test/test_creds.sh
    GLOBAL_BUCKET_ENV=foursight-cgap-mastertest-envs poetry run cli provision --trial --output_file out/foursight-dev-tmp/ --stage dev foursight --alpha --upload_change_set
