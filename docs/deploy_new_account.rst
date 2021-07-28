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

* If there's a base account to be used, for billing or administrative purposes, go to that account's `Organizations
  service <https://console.aws.amazon.com/organizations/home?#/accounts>`_. Then, add an account.

  Otherwise, create a new account from scratch, with billing information and contact information, from the `AWS login
  page <https://aws.amazon.com/>`_.

Note that the HMS email you use to create this account is treated as the 'root account' login.

* Once the account is created, you can request a password reset for a 'root account' login (not IAM login). When this
  is done, you'll be able to log into your new account with this password.

  The root account should not be used for routine use; an IAM user should be used for routine purposes.

* Create one new IAM user separate from the root account login, to be used to provision the rest of the account's
  resources. More information on this bootstrap step to be documented. As a result of this step, you should have this
  account's credentials in a configurable `.aws` directory, by default, `.aws_test/credentials`.

  In these instructions, we assume you'll be using test credentials in ``~/.aws_test``.
  If you're using credentials in locations, you may want to make ``~/.aws_test`` be a symbolic link
  to the one you are actively using.


Step Two: CGAP Orchestration with Cloud Formation
-------------------------------------------------

Note: you will need to request more elastic IPs from AWS,
as described
`here <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html>`_.

You can request this from the `Service Quotas console
<https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas>`_.

* Upload base templates required for starting the application.

::

    poetry run cli provision iam --validate --alpha --upload_change_set
    poetry run cli provision logging --validate --alpha --upload_change_set
    poetry run cli provision network --validate --alpha --upload_change_set
    poetry run cli provision ecr --validate --alpha --upload_change_set

    #############################################################################
    # This next command is a temporary workaround to manually create            #
    # AWSServiceRoleForAmazonElasticsearchService. This must be done before     #
    # datastore can be provisioned. In effect, you want to execute this         #
    # command, but with the right credentials in an isolated environment:       #
    #   aws iam create-service-linked-role --aws-service-name es.amazonaws.com  #
    # So this is the way to do that using docker.                               #
    #############################################################################
    docker run --rm -it -v ~/.aws_test:/root/.aws amazon/aws-cli iam create-service-linked-role --aws-service-name ecs.amazonaws.com

    ################################################################################
    # You will need to make sure you have an s3 encrypt key for your test account. #
    # You want to create this only one time and to be careful about where you      #
    # keep it. This script will store it in your ~/.aws_test/ directory as         #
    # s3_encrypt_key.txt and will set appropriate permissions so it is hard for    #
    # others to see and hard for you to accidentally delete. Other deployment      #
    # tools know to look for it in this location.                                  #
    ################################################################################
    make assure-s3-encrypt-key

    poetry run cli provision datastore --validate --alpha --upload_change_set

More info: https://docs.aws.amazon.com/elasticsearch-service/latest/developerguide/slr-es.html


These will take about fifteen minutes or so to finish provisioning, and should be run in order.
While they are instantiating, write the global application configuration in secrets manager.
There is more documentation on this is in ``docs/setup.rst``.

Once your new ECR comes online, upload an application image to it.
See the cgap-portal Makefile. Push the image tag specified in ``config.json`` prior to deploying ECS.

* Once all base stacks have finishing instantiating -- all stacks should be in state `UPDATE_COMPLETE` -- you can
  provision the application stack by doing::

     poetry run cli provision ecs --validate --alpha --upload_change_set


* Once the application has finishing instantiating, you can deploy the portal.

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

In this bucket, you will need to create a file corresponding to each environment you plan to use (probably just one).
So if your global application S3 bucket is ``myorg-foursight-cgap-myenv-envs`` then you will want to visit
that bucket in the AWS Console for S3 and upload a file that contains::

    {
        "fourfront": "<your-http-cgap-domain-here-with-no-trailing-slash>",
        "es": "<your-https-elasticsearch-url-here-with-:443-and-no-trailing-slash>",
        "ff_env": "<env-name>"
    }

The file ``.chalice/cgap-mastertest`` contains an example of what is loaded into our initial test account at
``s3://foursight-cgap-mastertest-envs/cgap-mastertest``, but the specific name of the bucket to load into is
different in each account because s3 namespacing requires that. Rather than manage this manually there
is an automatic tool to help.

To provision this bucket do::

    assure-global-bucket-env <env-name>

It should interactively confirm the environment that it will upload, and what account it will upload into.
If the global env bucket has not been created yet for that account, it will complain, but that should have
happened in the datastore stack.

You'll also need to initialize the foursight checks for your environment. This will create the file
``vendor/check_setup.py`` that you need for use with Foursight. To do this, do::

    resolve-foursight-checks

(The ``resolve-foursight-checks`` command copies ``check_setup.template.json`` into ``vendor/check_setup.json``,
replacing ``"<env-name>"`` with your chosen environment name, which is taken from the setting of ``ENCODED_BS_ENV``
in your ``config.json``.)

At this point, you should be ready to deploy foursight. To do so, use this command::

    source ~/.aws_test/test_creds.sh
    poetry run cli provision --trial --output_file out/foursight-dev-tmp/ --stage dev foursight --alpha --upload_change_set
    #############################################################################################################
    # NOTE: It should no longer be necessary to add an environment variable here, such as:                      #
    #       GLOBAL_BUCKET_ENV=foursight-cgap-mastertest-envs                                                    #
    #       Instead you should add entries for "GLOBAL_BUCKET_ENV" and "GLOBAL_ENV_BUCKET" to your config.json  #
    #       (The name is in transition, so for now please set both names. Eventually ony GLOBAL_ENV_BUCKET      #
    #       will be needed.)                                                                                    #
    #############################################################################################################

This will not entirely succeed on the first attempt. You'll need to run this a second time once various values have
been created.

At this point, Foursight should be working.

**NOTE:**
You may not be able to login without registering the generated domain with auth0.
To see the URL use::

    show-foursight-url

The output should look like::

    https://pme0nsfegf.execute-api.us-east-1.amazonaws.com/api/view/cgap-mastertest-kmp

To open the URL instead, use::

    open-foursight-url

