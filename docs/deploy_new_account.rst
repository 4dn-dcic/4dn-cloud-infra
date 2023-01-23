=======================
Deploying a New Account
=======================
Provisioning A C4 Cloud Infra Account From Scratch
--------------------------------------------------

This doc walks one through provisioning a c4 cloud infra account from scratch. If you already have configured your c4
cloud infra setup, and created an account with a basic IAM user provisioning, skip to Step Two.

Step Zero: Setup: Installation, and fill in config
--------------------------------------------------

First, see `<docs/setup.rst>`_ for detailed setup instructions.

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
  account's credentials in a configurable ``.aws``` directory, by default, ``.aws_test/credentials``.

  In these instructions, we assume you'll be using test credentials in ``custom/aws_creds`` (which can be a link to
  ``~/.aws_test`` if you're using our old paradigm). Using an in-repository directory will allow you to have different
  sandboxes with different credentials. For example, you may want to have multiple ``~/.aws_test.xxx`` folders and
  link the ``custom/aws_creds`` folder in any given sandbox to the appropriate credentials directory, that might be
  shared.

* Decide whether or not you would like this version of the system to be deployed with S3 encryption or not.
cgap-portal in its current form does not take PHI, and thus in theory does not need to encrypt any raw files
stored in S3. We have still implemented the ability to do so by setting an option in the ``config.json``
file, which you will setup in the next step.

* Note that an existing Auth0 account is assumed to be configured when deploying a new account. You will
  need to give the deployment configuration the following values::

    Auth0Domain
    Auth0ClientID
    Auth0Secret
    Auth0AllowedConnections

  For assistance with Auth0 configuration please contact the CGAP team directly.


Step Two: CGAP Orchestration with Cloud Formation
-------------------------------------------------

Note: you will need to request more elastic IPs from AWS,
as described
`here <https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/elastic-ip-addresses-eip.html>`_.

You can request this from the `Service Quotas console
<https://console.aws.amazon.com/servicequotas/home/services/ec2/quotas>`_.

* You will first need to use the initialization scripts to provision a ``custom`` directory containing configuration options for the CGAP environment you are deploying::

    init-custom-dir -h

The help command will give info on all the arguments you can pass to it - many will be prompted
for direct input upon running the command. Once you have completed this step you can begin building
the account.
The minimum arguments needed for `init-custom-dir` is `--credentials` which should be followed by the name of your defined local credentials; this is the `xxx` referred to above in the `~/.aws_test.xxx` directory name; for example: `init-custom-dir --credentials cgap-supertest` assuming you have an appropriate `~/.aws_test.cgap-supertest` directory.

* One note on network setup: the below commands will build a network for you with a default size of
  2 public and 2 private subnets, but you can configure this to be as big as you need within us-east-1.
  As of writing the largest network would have 6 subnets (us-east-1a, b, c, d, e, f). We recommend using
  only 2 when starting off and increasing the size later on by adding the ``subnet.pair_count`` value
  to ``config.json``.

* Upload base templates required for starting the application: note that you must manually execute
  change set from the Cloudformation console for each successive stack before moving onto the next::

    poetry run cli provision iam --validate --upload-change-set
    poetry run cli provision logging --validate --upload-change-set
    poetry run cli provision network --validate --upload-change-set
    poetry run cli provision ecr --validate --upload-change-set

    #############################################################################
    # This next command is a temporary workaround to manually create            #
    # AWSServiceRoleForAmazonElasticsearchService. This must be done before     #
    # datastore can be provisioned. In effect, you want to execute this         #
    # command, but with the right credentials in an isolated environment:       #
    #   aws iam create-service-linked-role --aws-service-name es.amazonaws.com  #
    # So this is the way to do that using docker. Note we also must do this for #
    # the ECS Service.                                                          #
    #############################################################################
    docker run --rm -it -v `pwd`/custom/aws_creds:/root/.aws amazon/aws-cli iam create-service-linked-role --aws-service-name es.amazonaws.com
    docker run --rm -it -v `pwd`/custom/aws_creds:/root/.aws amazon/aws-cli iam create-service-linked-role --aws-service-name ecs.amazonaws.com

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


Step Three (Intermission): Push a cgap-portal Image
---------------------------------------------------

**NOTE:** This step is done from the ``cgap-portal`` repo. You probably want to
create a CodeBuild project to expedite the build process, but you can build/push
an image manually from your local machine. We strongly recommend use of CodeBuild. Note
that you cannot build using CodeBuild until the network has come online.

Once your new ECR comes online, upload an application image to it.
See the cgap-portal Makefile. Push the image tag specified in ``config.json`` prior to deploying ECS.

To use CodeBuild, create a Github Personal Access Token and add it to your
``secrets.json`` file ie::

    {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "github_pat_abcd1234"
    }

Note that you CANNOT use fine-grained access tokens at this time. They do not work with CodeBuild.
Use a legacy token and give it "repo" permissions. Once this is set you can trigger the stack build
for CodeBuild::

    poetry run cli provision codebuild --validate --upload-change-set

This will create a new CodeBuild job that will use your personal access token to clone
the default repository. You change the repository to build by setting ``codebuild.repo_url`` in your
``config.json`` file.

Execute this change set, after which a CodeBuild job for building the portal will be
available. There will be 3 build jobs generated by the CodeBuild stack - one for Tibanna,
one for the portal (the name of the environment you specified) and one for pipelines.
From the CodeBuild console, trigger the job named by your environment and the master branch
will be built and pushed to your ECR.

Note that once Foursight is online you can trigger new builds of all CodeBuild jobs from the ``Trigger
CodeBuild Run`` check.


Step Four: Fill out any remaining application secrets
-----------------------------------------------------

* Many secrets are pre-filled, but some will need to be set. Running the command ``setup-remaining-secrets``
will guide you through the process. More information on the secrets themselves and how to manually set
this up follows. if the prior command works without issue, you can move on to the next section.

  * Go to the Secrets Manager

  * There are two secrets. Information from the RDS secret will be needed in this action, but we'll start in the
    one with a longer name, like ``C4AppConfigCgapSupertest``, where ``CgapSupertest``
    is what in this example corresponded to a ``cgap-supertest`` environment. You may have named your environment
    differently, so the name you see will vary.  Click into the environment-related resource.

  * Find the page section called ``Secret value`` and click on ``Retrieve secret value``.

  * You can now see the secret but you'll need to edit it. Click ``Edit``.

  * You'll now have to do a scavenger hunt to obtain values for anything marked ``XXX: ENTER VALUE``.

    * The ``S3_AWS_ACCESS_KEY_ID`` is generated by you from the S3 IAM user page.
      This is not your AWS access key ID, but the ID of the daemon user that will run the CGAP application.

    * The ``S3_AWS_SECRET_ACCESS_KEY`` is generated by you from the S3 IAM user page.
      This is not your AWS secret access key, but the key of the daemon user that will run the CGAP application.

      **Please observe proper security protocols while holding this secret on your local machine.**

    * The ``ENCODED_ES_SERVER`` will look like::

         vpc-os-cgap-supertest-a1b2c3d4e5f6etc.us-east-1.es.amazonaws.com:443

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

      * Go to `the Secrets Manager in the AWS console
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


Step Five: CGAP Portal Orchestration
------------------------------------

* Ensure that you have set the ``identity`` and ``s3.encrypt_key_id`` (if applicable) variables in ``config.json``.

* Once all base stacks have finishing instantiating -- all stacks should be in state ``UPDATE_COMPLETE`` -- you can
  provision the application stack by doing::

     poetry run cli provision ecs --validate --upload-change-set

* Before executing the ECS stack, you need to provision a basic environment configuration. Do
  so by running the ``assure-global-env-bucket`` script. It will confirm some structure for you
  that you can approve before uploading. Once this is done you can execute change set on the
  ECS stack in the CloudFormation console.

* Once the application has finishing instantiating, you can deploy the portal. To check that the portal
  is up and running, navigate to the ECS stack outputs, find the load balancer URL and go to ``/health?format=json``.
  If the health page comes up you are in good shape.

Deploying CGAP (Initial)
~~~~~~~~~~~~~~~~~~~~~~~~

To deploy the CGAP portal you have uploaded:

* Ensure that it is the end of the day, if possible, as the initial provisioning takes a few hours to complete and
  other core application services (Foursight, Tibanna) will not be available until access keys are loaded (at the
  end of the deployment action). This is important to note if you are re-issuing the initial deployment, as core
  services will not work entirely until the deployment finishes.

* If doing a custom deploy, ensure that you have filled out ``ENCODED_DATA_SET`` and ``ENCODED_ADMIN_USERS`` correctly. Without this set, users from DBMI will be loaded into your
environment instead of your users and you will not be able to access the portal. To do this, use
``ENCODED_DATA_SET="custom"``. Example structure for ``ENCODED_ADMIN_USERS`` is automatically generated
by the new config setup command ie::

    "ENCODED_ADMIN_USERS": [
        {
            "first_name": "John",
            "last_name": "Smith",
            "email": "john_smith@example.com"
        }
    ]

* Note that once Foursight has been built, you can run future deployments from the ``Invoke an ECS Task`` check.
Use information from the ``ECS Status`` and ``ECS Task Listing`` checks and the Networking tab to pass
appropriate arguments.

* Navigate to `the ECS console in AWS <https://console.aws.amazon.com/ecs/home?region=us-east-1#/taskDefinitions>`_.

* Select `the Task Definitions tab <https://console.aws.amazon.com/ecs/home?region=us-east-1#/taskDefinitions>`_.

* Check the radio button next to the task name itself for the task that has ``InitialDeployment`` in its name.
  (It will be a more complicated name like ``c4-ecs-stack-CGAPInitialDeployment-uhQKq2UsJoPx``, but there is only
  one with ``InitialDeployment`` in its name.)

  NOTE WELL: This is _not_ the task just named ``Deployment``. Make sure it says ``InitialDeployment``.
  Ensure you run this initial task at the end of the day, as it takes a long time to run and other application
  services such as Foursight and Tibanna will be unavailable until it finishes. You can use this
  ``InitialDeployment`` task to clear the database and start from base deploy inserts.

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

Note that a routine deployment must run every 90 days to cycle admin access keys. All access keys expire
after 90 days. Foursight has a check that will alert you of this as admin keys approach expiration.

Step Six: Deploying Foursight
-----------------------------

Foursight is a serverless application we use to outsource many infrastructure management tasks out
of AWS to simplify the maintenance of the application.

You'll need to initialize the foursight checks for your environment. This will create the file
``vendor/check_setup.py`` that you need for use with Foursight. To do this, do::

    resolve-foursight-checks

By default, the ``resolve-foursight-checks`` command copies foursight-cgap's ``check_setup.json`` into ``vendor/check_setup.json``,
replacing ``"<env-name>"`` with your chosen environment name, which is taken from the setting of ``ENCODED_ENV_NAME``
in your ``config.json``. If a different check configuration is desired, run the command
with the ``--template_file`` argument set accordingly, e.g.::

   resolve-foursight-checks --template_file <path to check file>


At this point, you should be ready to deploy foursight. To do so, use this command::

    source custom/aws_creds/test_creds.sh
    ln -s app-cgap.py app.py
    poetry run cli provision foursight --upload-change-set --stage prod


* Go to the console and execute the change set.

* Once the changeset has finished executing, check the stack outputs to see the URL and attempt to
  login with your admin user to ensure all is working. Running the ``ECS Status`` and ``ECS Task Listing``
  checks will give some info as well to test that all is well.

**NOTE:**
You may not be able to login without registering the generated domain with auth0 as a callback URL.
To see the URL use::

    show-foursight-url

The output should look like::

    https://pme0nsfegf.execute-api.us-east-1.amazonaws.com/api/view/cgap-supertest

To open the URL instead, use::

    open-foursight-url

Note that if you have orchestrated with S3 + KMS encryption enabled see `<docs/encryption.rst>`_
for additional needed setup.

Step Seven: Deploying Tibanna Zebra
-----------------------------------

Now it is time to provision Tibanna in this account for CGAP. Ensure test creds are active, in particular::

    GLOBAL_ENV_BUCKET
    S3_ENCRYPT_KEY
    S3_ENCRYPT_KEY_ID (if using)
    ACCOUNT_NUMBER

then deploy Tibanna. Note that all of the following steps
take some significant time so should be run in parallel if possible. Note additionally that the
credentials for the account you're deploying into must be active for all subsequent steps::

    source custom/aws_creds/test_creds.sh
    tibanna_cgap deploy_zebra --subnets <private_subnets> -r <application_security_group> -e <env_name>

In the following steps, you don't have to re-run the ``source`` command to get new of your credentials,
*but* it's very critical
that this be done so you're not posting to the wrong account. As such, we show that step redundantly at
each point.

If you have ENV_NAME set correctly as an environment variable, you can accomplish this by doing::

    source custom/aws_creds/test_creds.sh
    tibanna_cgap deploy_zebra --subnets `network-attribute PrivateSubnetA` -e $ENV_NAME -r `network-attribute ApplicationSecurityGroup`


While the tibanna deploy is happening, you may want to do this next step in another shell window.

**IMPORTANT NOTE:**  If you use a different shell, **it is critical** that you re-select the same directory
as you were in (your ``4dn-cloud-infra`` repository) **and also** re-run the ``source`` command
to get new credentials in that window. Even if you think it's redundant, it's advisable to do it anyway to
avoid error. It's very low-cost and avoids a lot of headache.

For this next step, you need the ``aws`` command line operation to be functioning. If you have any problems with
that, you may need to run this script::

    scripts/assure-awscli

Next you'll need to transfer the public reference files from the 4DN main account buckets into the new
account files bucket. This step can take as much as 45-60 minutes if you have not previously copied some or
all of the indicated files::

    source custom/aws_creds/test_creds.sh
    aws s3 sync s3://cgap-reference-file-registry s3://<new_application_files_bucket>

Note that you can locate the "files" bucket by examining the application configuration or the portal health page.

Then, clone the `cgap-pipeline-main` repo, checkout the version you want to deploy (v1.1.0 as of writing) and upload
the bioinformatics metadata to the portal. (This example again assumes the environment variable ENV_NAME
is set correctly. If you have already sourced your credentials, that part doesn't have to be repeated, but
it's critical to have done it, so we include that here redundantly to avoid problems.) ECR images will also
be posted, so ensure ``$AWS_REGION`` is set.::

    source custom/aws_creds/test_creds.sh
    make deploy-all

If you built the CodeBuild stack, this deploy should go fairly quickly as it will trigger many
simultaneous builds on CodeBuild for all the various repositories.

Finally, push the tibanna-awsf image to the newly created ECR Repository in the new account::

    ./scripts/upload_tibanna_awsf

Note that you can trigger the awsf image build through CodeBuild (or foursight) as well if using the
CodeBuild stack.

Once the above steps have completed after 20 mins or so, it is time to test it out. Navigate to
Foursight and trigger the md5 check - this will run the md5 step on the reference files. You should be able
to track the progress from the Step Function console or CloudWatch. It should not take more than a few minutes
for the small files. Once this is done, the portal is ready to analyze cases. One should consider requesting an
increase in the spot instance allocation limits as well if the account is intended to run at scale.

For HMS internal use, You might need to make the  ``Settings.HMS_SECURE_AMI`` available or
specify a new AMI for use. Add the new
account number you are deploying in to the set of account IDs that the secure AMI is shared with (6433).

Step Eight: NA12879 Demo Analysis
---------------------------------

NOTE: this step relied on a now defunct CGAP environment. Proceed to step nine.

With Tibanna deployed we are now able to run the demo analysis using NA12879. The raw files for this case are
transferred as part of the reference file registry, so we just need to provision the metadata.::

    poetry run fetch-file-items GAPCAKQB9FPJ --post --keyfile ~/.cgap-keys.json --keyname-from fourfront-cgap --keyname-to <new_env_name>
    poetry run submit-metadata-bundle test_data/na_12879/na12879_accessioning.xlsx --s <portal_url>

At this point you have a case for the NA12879 WGS Trio analysis and can upload a MetaWorkflowRun
(meta_wfr) for the pipeline run. Use the provided command to create a meta_wfr for the demo
analysis.::

    poetry run create-demo-metawfr <case_uuid> --post-metawfr --patch-case

Once this is done, navigate to Foursight and execute the ``Metawfrs to run`` check and associated
action, which will kick the pipeline. If a step fails due to spot interruption or other failure,
you can re-kick the failed steps by executing the ``Failed Metawfrs`` check and associated action.
The steps will restart on the next automated run of the ``Metawfrs to run`` check, which runs
every 15 minutes. You can manually run this check and associated action to immediately trigger
the restart.

Once the output VCF has been ingested, the pipeline is considered complete and variants can be
interpreted through the portal.

Step Nine: Deploy/Enable Higlass
--------------------------------

NOTE: using a custom Higlass server requires a valid HTTPS certificate on the load balancer. If you
do not want to configure this right away, let us know and we can let you use ours while you try out
CGAP. If you're prepared with a certificate, feel free to proceed with the Higlass setup.

If running an external orchestration, you will need to deploy a Higlass server to an EC2 instance.
You can do this automatically by running the provision command::

    poetry run cli provision higlass --upload-change-set

Execute the change set and give some time for it to spin up.

In order for Higlass views to work, some CORS configuration is required. Add the following CORS policy
to the ``wfoutput`` bucket (for bam visualization), replacing the sample
MSA URL with the new URL.::

    [
        {
            "AllowedHeaders": [
                "*"
            ],
            "AllowedMethods": [
                "GET"
            ],
            "AllowedOrigins": [
                "https://cgap-supertest.hms.harvard.edu"
            ],
            "ExposeHeaders": []
        }
    ]

You will also need to update the CORS configuration on
the cgap-higlass bucket in the main account (6433). Add
the new environment CNAME to the allowed origins.

Step Ten: Open Support Tickets
------------------------------

Open a support ticket to request an increase in the spot instance capacity. Namely, ask for
a spot instance limit increase to a significantly higher vCPU value (such as 9000).

Step Eleven: Configure HTTPS
----------------------------

Production environments require HTTPS. There are several steps required to
enabling HTTPS connections to CGAP, and some important caveats. The most
important detail to note is that at this time we terminate HTTPS at the
Application Load Balancer in our public subnets. This means that HTTP traffic
is traveling unencrypted within our network to portal API workers. Full
end-to-end encryption on that path is not supported at this time, but is a
high priority feature.

First, note the DNS A Record of the Load Balancer created. This record will
be needed for registering a CNAME.

If you're an internal user, DBMI IT has a small form you can fill out
to request a CNAME record for the desired domain. You want this new
domain to point to the A record of the load balancer. Once acquired, you
should then be able to send HTTP traffic to the new CNAME. At this point,
generate a CSR for the new domain and send it to DBMI IT, who will respond
with the certificate. Import the certificate into ACM and associate it with
the load balancer. Modify the listener rule on the load balancer for port 80
to automatically redirect all HTTP traffic to HTTPS.

Note that there is additional internal documentation on this process in
Confluence.

Note additionally that Nginx configuration updates may be necessary,
especially if using non-standard domains (see cgap-portal nginx.conf).

Once the certificate has been enabled, modify the port 80 load balancer
listener to redirect HTTP traffic to HTTPS. Note that this will effectively
disable the load balancer URL - update the foursight environment file to use
the HTTPS URL to account for this (the files created in S3 by ``assure-global-env-bucket``).

Final Notes
-----------

At this point, the orchestration of CGAP is complete. To run through important things you should have
built briefly:

* An isolated network for CGAP to use
* S3 buckets that CGAP will put data into
* Some Secrets in SecretsManager that CGAP will use to gather configuration
* Some compute resources (OpenSearch, RDS) that CGAP uses to store metadata
* An ECS Cluster for running the CGAP application/API, with necessary starter data loaded in
* A Lambda application (Foursight) for admins to use to help maintain CGAP
* A Step Function (Tibanna) made up of Lambda functions for managing workflows
* Several ECR repositories for the CGAP application, tibanna and various pipelines
* Several log groups in CloudWatch for debugging issues with CGAP

All components work together to accomplish tasks. Most issues occur because a setup instruction is
incomplete or did not go through correctly. Please feel free to report issues to us directly as they
come up as it is probable we will be able to guide you to a fix quickly.

Note that the cost of running a barebones system should be on the order of $500 a month or so. As
you scale up and analyze more files the storage cost will go up while compute costs will remain the same.
Once you reach a large enough size (millions of variants) you may need to scale up the database or
the ElasticSearch to performance remains stable. We've run CGAP with millions of variants and use a
single t4g.xlarge instance for the database and 3 c6g.xlarge.elasticsearch nodes for the ElasticSearch
cluster (no master nodes). If you're going to scale beyond this, it's probably a good idea to talk with
the CGAP team first.

Common Issues
-------------

Higlass tracks do not load.

    * Check CORS configuration on the ``wfoutput`` bucket in S3
    * Check that your higlass server is responding to API requests
    * If not using our server, double check your certificate is working correctly
    * Check the higlass_view_config items have the correct server URLs (if not using ours)
    * Check with us that we have properly configured our internal higlass server so you can use it
      (if using ours in a trial)

Internal Server Error/502 Error loading CGAP Portal

    * Check CGAPDocker log group in CloudWatch to ensure the application can start up. Usually failures
      at startup are because the application configuration has not been filled out correctly.
    * Check that you have run the initial deployment - the UI will not load until ES mappings have
      been generated as part of the deployment task
    * Check ``/health?format=json`` and ``/counts?format=json``. Using ``?format=json`` will disable loading of the UI. If ES
      has items in it and UI still will not load please screenshot the JS console and send us a bug
      report. Also check that the CodeBuild job for the portal completed successfully, particularly
      the NPM build. See the cgap-portal repositories top-level
      ``Dockerfile``
    * Check that ``GLOBAL_ENV_BUCKET`` is set correctly in the application configuration, and that
      appropriate entries exist in S3. You should have environment information in ``main.ecosystem``
      and another file named your environment that directs its configuration to ``main.ecosystem``.
    * If using encryption, check that the KMS key permissions are correct. Note that there is a command
      ``update-kms-policy`` that will handle this for you. See the ``encryption.rst`` document for more
      detailed information.

Internal Server Error loading Foursight

    * Check FoursightAPIHandler logs to see what the error is.
    * Check that ``GLOBAL_ENV_BUCKET`` is set correctly in the application configuration, and that
      appropriate entries exist in S3.
    * Check that the Foursight build was successful (look at output of ``provision`` command)

Cannot login to CGAP/Foursight

    * Check that appropriate callback URLs have been added to your Auth0 Configuration
    * Ensure that you have run the Initial Deployment using ``custom`` deployment inserts and that
      you have set the ``ENCODED_ADMIN_USERS`` value in the application configuration. Further users
      can be added from the Foursight users page.

Tibanna jobs fail

    * In the step function console, the failed job should have a job ID and a traceback. Examine the
      traceback to see if it is AWS related or otherwise. If not due to AWS, feel free to send a bug
      report.
    * If the failure occurred during job execution, in your 4dn-cloud-infra venv run ``tibanna log --job-id <jid>``
      to get detailed information from the failed job. If the error is not related to job inputs, feel
      free to send us a bug report.
    * Check Lambda logs for the various lambdas in the step function to ensure no crashes/errors are
      occurring there. Those can also be reported to us in a bug report.
    * Check that all references files were successfully sync'd to your files bucket.
