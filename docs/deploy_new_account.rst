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

  In these instructions, we assume you'll be using test credentials in ``custom/aws_creds`` (which can be a link to
  ``~/.aws_test`` if you're using our old paradigm). Using an in-repository directory will allow you to have different
  sandboxes with different credentials. For example, you may want to have multiple ``~/.aws_test.xxx`` folders and
  link the ``custom/aws_creds`` folder in any given sandbox to the appropriate credentials directory, that might be
  shared.


Step Two: CGAP Orchestration with Cloud Formation
-------------------------------------------------

Note: you will need to request more elastic IPs from AWS,
as described
`here <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html>`_.

You can request this from the `Service Quotas console
<https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas>`_.

* Upload base templates required for starting the application::

    poetry run cli provision iam --validate --upload_change_set
    poetry run cli provision logging --validate --upload_change_set
    poetry run cli provision network --validate --upload_change_set
    poetry run cli provision ecr --validate --upload_change_set

    #############################################################################
    # This next command is a temporary workaround to manually create            #
    # AWSServiceRoleForAmazonElasticsearchService. This must be done before     #
    # datastore can be provisioned. In effect, you want to execute this         #
    # command, but with the right credentials in an isolated environment:       #
    #   aws iam create-service-linked-role --aws-service-name es.amazonaws.com  #
    # So this is the way to do that using docker.                               #
    #############################################################################
    docker run --rm -it -v `pwd`/custom/aws_creds:/root/.aws amazon/aws-cli iam create-service-linked-role --aws-service-name es.amazonaws.com

    ################################################################################
    # You will need to make sure you have an s3 encrypt key for your test account. #
    # You want to create this only one time and to be careful about where you      #
    # keep it. This script will store it in your ./custom/aws_creds directory as   #
    # s3_encrypt_key.txt and will set appropriate permissions so it is hard for    #
    # others to see and hard for you to accidentally delete. The script will tell  #
    # you the name of the key that you need to assure you add to your secrets in   #
    # ./custom/secrets.json so that you can use it consistently going forward.     #
    #                                                                              #
    # NOTE WELL: Use the --verbose options ONLY interactively since it will        #
    #   output a secret that you should not capture in a script or log.  If you    #
    #   want to put this into a file for error-checking purposes, don't use        #
    #   the --verbose arg.                                                         #
    ################################################################################
    ./scripts/assure_s3_encrypt_key --verbose

    poetry run cli provision datastore --validate --upload-change-set

More info: https://docs.aws.amazon.com/elasticsearch-service/latest/developerguide/slr-es.html


These will take about fifteen minutes or so to finish provisioning, and should be run in order.
While they are instantiating, write the global application configuration in secrets manager.
There is more documentation on this is in ``docs/setup.rst``.


Step Three (Intermission): Push a cgap-portal Image
---------------------------------------------------

**NOTE:** This step is done from the ``cgap-portal`` repo.

* Once your new ECR comes online, upload an application image to it.
  See the cgap-portal Makefile. Push the image tag specified in ``config.json`` prior to deploying ECS.


Step Four: Fill out any remaining application secrets
-----------------------------------------------------

* Many secrets are pre-filled, but some will need to be set.

  * Go to the Secrets Manager

  * There are two secrets. Information from the RDS secret will be needed in this action, but we'll start in the
    one with a longer name, like ``C4DatastoreApplicationConfigurationCgapSupertest``, where ``CgapSupertest``
    is what in this example corresponded to a ``cgap-supertest`` environment. You may have named your environment
    differently, so the name you see will vary.  Click into the environment-related resource.

  * Find the page section called ``Secret value`` and click on ``Retrieve secret value``.

  * You can now see the secret but you'll need to edit it. Click ``Edit``.

  * You'll now have to do a scavenger hunt to obtain values for anything marked ``XXX: ENTER VALUE``.

    * The ``AWS_ACCESS_KEY_ID`` is obtained from your system administrator.
      This is not your AWS access key ID, but the ID of the daemon user that will run the CGAP application.

    * The ``AWS_SECRET_ACCESS_KEY`` is obtained from your system administrator.
      This is not your AWS secret access key, but the key of the daemon user that will run the CGAP application.

      **Please observe proper security protocols while holding this secret on your local machine.**

    * The ``ENCODED_ES_SERVER`` will look like::

         vpc-es-cgap-supertest-a1b2c3d4e5f6etc.us-east-1.es.amazonaws.com:443

      You can obtain it by this procedure:

      * Go to `the ElasticSearch service in the AWS console
        <https://console.aws.amazon.com/es/home?region=us-east-1#>`_.
      * Click into the service for your environment. (There is usually only one.)
      * Copy the ``VPC Endpoint`` but

        * Remove the initial ``https://``.
        * Remove any trailing slash.
        * Add ``:443`` at the end.

    * The ``ENCODED_IDENTITY`` is the name of the secrets resource itself. It's the non-RDS secret you are
      filling out. It will look something like
      ``C4DatastoreCgapSupertestApplicationConfiguration``.

    * The ``RDS_HOSTNAME`` is obtained from the RDS secret in the Secrets Manager that
      you passed by in getting to this page.

      You can obtain it by this procedure:

      * Go to ``the Secrets Manager in the AWS console
        <https://console.aws.amazon.com/secretsmanager/home?region=us-east-1#!/listSecrets>`_.
      * Click into the resource with a name like ``C4DatastoreRDSSecret``.
      * In the page section called ``Secret value``, click on ``Retrieve secret value``.
        (You do not need to press ``Edit`` here.)
      * The value named ``host`` is the value for ``RDS_HOSTNAME`` in the other secret we are constructing.
      * The value named ``password`` will be needed for ``RDS_PASSWORD`` in that other secret.

    * The ``RDS_PASSWORD`` also comes from the RDS secret in the Secrets Manager. See item immediately above.

      **Please observe proper security protocols while holding this secret on your local machine.**

    * The ``SENTRY_DSN`` is empty. You don't need to fill this for the system to work, but it won't connect to
      Sentry unless you supply this.

      A Sentry account allows you to partition its alerting capabilities on a per-tracked-resource basis
      using what it calls a Domain Source Identifier (DSN). Such setup is beyond the scope of this document.


Step Five: More CGAP Orchestration with Cloud Formation
-------------------------------------------------------

* Once all base stacks have finishing instantiating -- all stacks should be in state `UPDATE_COMPLETE` -- you can
  provision the application stack by doing::

     poetry run cli provision ecs --validate --upload-change-set


* Once the application has finishing instantiating, you can deploy the portal.

Deploying CGAP (Initial)
~~~~~~~~~~~~~~~~~~~~~~~~

To deploy the CGAP portal you have uploaded:

* Ensure that it is the end of the day, if possible, as the initial provisioning takes a few hours to complete and
  other core application services (Foursight, Tibanna) will not be available until access keys are loaded (at the
  end of the deployment action). This is important to note if you are re-issuing the initial deployment, as core
  services will go down until the deployment finishes.

* Navigate to `the ECS console in AWS <https://console.aws.amazon.com/ecs/home?region=us-east-1#/taskDefinitions>`_.

* Select `the Task Definitions tab <https://console.aws.amazon.com/ecs/home?region=us-east-1#/taskDefinitions>`_.

* Check the radio button next to the task name itself for the task that has ``InitialDeployment`` in its name.
  (It will be a more complicated name like ``c4-ecs-stack-CGAPInitialDeployment-uhQKq2UsJoPx``, but there is only
  one with ``InitialDeployment`` in its name.)

  NOTE WELL: This is _not_ the task just named ``Deployment``. Make sure it says ``InitialDeployment``.
  Ensure you run this initial task at the end of the day, as it takes a long time to run and other application
  services such as Foursight and Tibanna will be unavailable until it finishes. You can use this
  ``InitialDeployment`` task to clear the database and start from base deploy inserts (on cgap-devtest only).

* With the radio button for the ``InitialDeployment`` item checked, an ``Actions`` pull-down menu should appear
  at the top. Pull that down to find a Run Task Action and select that to invoke the task. (It will still need to
  ask you some questions.)

* Trying to run the task will prompt you for various kinds of data on a separate page.

  * Select a ``Launch type`` of ``FARGATE``.

  * As a ``Cluster VPC``, select the one named ``C4NetworkVPC`` (at the ``10.x.x.x`` IP address).

  * For ``Subnets``, make sure to select both *private* subnets (and *not* the public ones).

  * For ``Security groups``, select ``Edit``. This will take you to a new page that lets you set values:

    * Choose ``Existing Security Group``
    * Select the group named ``C4NetworkDBSecurityGroup``.
    * Select the group named ``C4NetworkApplicationSecurityGroup``.
    * Select the group named ``C4NetworkHTTPSSecurityGroup``.
    * Once all security groups are selected, click ``Save`` at the bottom to return to where
      you were in specifying task options.

  * For ``Auto-assign public IP``, select ``DISABLED``.

  * Once all of these are set, click ``Run Task`` at the bottom right of the page.

**NOTE:** In the future, we hope to have an automated script for setting all of this.

At this point you'll have to wait briefly for provisioning. You can navigate back to
`the Clusters tab of the ECS console in AWS <https://console.aws.amazon.com/ecs/home?region=us-east-1#/clusters>`_,
and select the stack you're building. It might have a name that looks like
``c4-ecs-stack-cgapsupertest-Id3abyB8OGv1``.  On the page for that stack, select the ``Tasks`` tab,
you can see the status of running tasks. Wait for them to not be in state ``PROVISIONING``.

With this task run, once the deployment container is online,
logs will immediately stream to the task, and Cloudwatch.

Deploying CGAP (Routine)
~~~~~~~~~~~~~~~~~~~~~~~~

Nearly all of the above information for the ``InitialDeployment`` task is the same for "routine" deployments.
Use the ``DeploymentTask`` to run "standard" CGAP deployment actions, including ElasticSearch
re-mapping and access key rotation. Routine deployment should be run every time a change to the data model is made,
but should in the meantime just be put on an automated schedule like our legacy deployments.

Step Six: Finalizing CGAP Configuration
----------------------------------------

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

    source custom/aws_creds/test_creds.sh
    poetry run cli provision foursight --upload-change-set
    #############################################################################################################
    # NOTE: It should no longer be necessary to add an environment variable here, such as:                      #
    #       GLOBAL_BUCKET_ENV=foursight-cgap-mastertest-envs                                                    #
    #       Instead you should add entries for "GLOBAL_BUCKET_ENV" and "GLOBAL_ENV_BUCKET" to your config.json  #
    #       (The name is in transition, so for now please set both names. Eventually ony GLOBAL_ENV_BUCKET      #
    #       will be needed.)                                                                                    #
    #       It should also no longer be necessary to provide --output-file out/foursight-dev-tmp/ --stage dev   #
    #       on the command line because these are now the default for this provision operation.                 #
    # NOTE: Will wants an explanation of 'dev' vs 'prod' here.                                                  #
    #############################################################################################################

* Go to the console and execute the change set.

**NOTE WELL:** This will ALWAYS not entirely succeed on the first attempt.
Some information is only available after completely executing the first change set.
We'll change that in the future.
For now, you'll need to run this a second time once various values have been created.

* Deploy the deployment action a second time, same as the first::

   poetry run cli provision foursight --upload-change-set

* Of course you'll have to go to the console and execute the change set.

At this point, Foursight should be working.

**NOTE:**
You may not be able to login without registering the generated domain with auth0.
To see the URL use::

    show-foursight-url

The output should look like::

    https://pme0nsfegf.execute-api.us-east-1.amazonaws.com/api/view/cgap-mastertest-kmp

To open the URL instead, use::

    open-foursight-url

Step Seven: Deploying Tibanna Zebra
-----------------------------------

Now it is time to provision Tibanna in this account for CGAP. Ensure test creds are active, in particular the
correct ``GLOBAL_BUCKET_ENV`` and ``S3_ENCRYPT_KEY`` and deploy Tibanna.::

    source custom/aws_creds/test_creds.sh
    tibanna_cgap deploy_zebra --subnets <private_subnet> -r <application_security_group> -e <env_name>

While this is happening, transfer the public reference files from the 4DN main account buckets into the new
account files bucket.::

    aws s3 sync s3://cgap-reference-file-registry s3://<new_application_files_bucket>

Then, clone the cgap-pipeline repo, checkout the version you want to deploy (v24 as of writing) and upload
the bioinformatics metadata to the portal.::

    python post_patch_to_portal.py --ff-env=<env_name> --del-prev-version --ugrp-unrelated

Once the aboe 3 steps have completed after 20 mins or so, it is time to test it out. Navigate to
Foursight and trigger the md5 check - this will run the md5 step on the reference files. You should be able
to track the progress from the Step Function console or CloudWatch. It should not take more than a few minutes
for the small files. Once this is done, the portal is ready to analyze cases.

Step Eight: NA12879 Demo Analysis
---------------------------------

NOTE: this step requires access keys to current CGAP production (cgap.hms.harvard.edu).

With Tibanna deployed we are now able to run the demo analysis using NA12879. The raw files for this case are
transferred as part of the reference file registry, so we just need to provision the metadata.::

    poetry run fetch-file-items GAPCAKQB9FPJ --post --keyfile ~/.cgap-keys.json --keyname-from fourfront-cgap --keyname-to <new_env_name>
    poetry run submit-metadata-bundle test_data/na_12879/na12879_accessioning.xlsx --s <portal_url>

TODO: document pipeline kick
