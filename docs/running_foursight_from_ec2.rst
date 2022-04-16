===================================
Running Foursight "Locally" via EC2
===================================

To run foursight checks/actions on a deployment environment manually, an EC2 within
the deployment's network must be created and configured appropriately.

There are many possible routes to the same end here as outlined below; for an example
script to get up and running immediately, see the end of this document.

**Note**: We assume the EC2 is running an Ubuntu-based OS.

Configuration Steps
===================

Step One: Launch an EC2 within deployment's network
---------------------------------------------------

This can be done manually via the AWS Console or scripted out if desired. Utilizing an
IAM role is highly recommended to simplify AWS credential handling/expiration.

For more details, see the 4DN-DCIC Confluence site.


Step Two: Configure EC2 with this repository
--------------------------------------------

This step can be performed in either of the following manners:

* Copy local repository to EC2 instance via:

        ``scp -r -i <path to PEM> <path to local repository> ubuntu@<EC2 public address>:~``.

  - Ensure appropriate, up-to-date credentials are linked via *custom* directory, as
    symlinks are fully expanded with ``scp`` (consider using ``rsync`` to maintain
    symlinks, if desired).

* Clone repository to EC2 instance.

  - This will be performed automatically by this repo's configuration script.
  - **Note**: GitHub credentials may need to be configured on EC2 first. This is
    recommended if debugging foursight so commits can be pushed.
  - **Note**: An appropriately configured *custom* folder must be included in the
    repository (likely via ``scp``) if certain environmental variables not set; see Step
    Six below.

If using this repo's EC2 configuration script, the repo should be located in the home
directory.


Step Three: Configure EC2 Python environment
--------------------------------------------

The EC2 will need a minimum of acceptable versions of Python and poetry. This
repository's *scripts/local_testing_ec2_setup.sh* script utilizes pyenv tools to
configure a virtual environment with all required packages; see the script for details.

As pyenv and poetry require proper environmental variables to function, these will be
set by the script and added to the shell configuration file. If running the script
within an interactive shell, the variables can be set via:

    ``source ~/4dn-cloud-infra/scripts/local_testing_ec2_setup.sh``

or via:

    ``sh ~/4dn-cloud-infra/scripts/local_testing_ec2_setup.sh``
    ``source ~/.bashrc``.

Note the modification of this repo's *pyproject.toml* within the script above to
install foursight locally, enabling on-the-fly debugging and changes to be incorporated
when running checks/actions.


Step Four: Checkout foursight branch of interest
------------------------------------------------

Even if not utilizing a development branch with changes to checks/actions, it is still
recommended to checkout a branch to prevent commits to master.


Step Five: Update check_setup.json
------------------------------------

Create the appropriate *check_setup.json* for the environment of interest to use for
checks/actions via:

        ``poetry run resolve-foursight-checks``.

**Note**: If adding or deleting checks/actions, be sure to modify the foursight repo's
check setup file prior to the above.


Step Six: Ensure up-to-date AWS variables available
------------------------------------------------------

To run checks/actions, the following environmental variables **must** be set
appropriately:

* ``S3_ENCRYPT_KEY``
* ``AWS_DEFAULT_REGION`` (or *~/.aws* configured appropriately)
* ``AWS_ACCESS_KEY_ID``, ``AWS_SECRET_ACCESS_KEY``, ``AWS_SESSION_TOKEN`` (or IAM role
  appropriately configured)

If this repository does not have a configured *custom* directory, the following
variables will also need to be set:

* ``GLOBAL_ENV_BUCKET``
* ``ES_HOST``
* ``ENV_NAME``

Some of these variable you may be able to source from *custom/aws_creds/test_creds.sh*,
but beware of setting expired AWS credentials with this route, especially if the EC2 is
configured with an IAM role.


Step Seven: Run check script
----------------------------

Before launching a Jupyter notebook to run checks/actions, ensure all necessary
configuration has succeeded by running a default check via:

        ``python foursight_local/run_check_and_action.py``

from the root of this repository.

If the check fails to run successfully, check the traceback.
Lack of appropriate environmental variables can cause inexplicit errors, so start by
checking the variables above are set appropriately if uncertain of the error raised.


Step Eight (optional): Launch Jupyter notebook and run checks/actions or debug
------------------------------------------------------------------------------

As running checks/actions with a Jupyter notebook is often preferred, this can be
accomplished by starting the notebook on the EC2 instance via the command

        ``python -m notebook --no-browser --port=8888``

from the root of this repository (with the port option of your preference). Then, on
the local computer, connect to the EC2 via

        ``ssh -N -L localhost:8888::localhost:8888 -i <path to PEM> ubuntu@<EC2 address>``

with the ports updated as required.


Example Umbrella Script
=======================

For a direct, no-frills configuration that should permit quick access to running checks/
actions, consider using the template script below and meeting its assumptions.

Note the path to the local 4dn-cloud-infra repo must be filled in, and the following
environmental variables must be set correctly:

* ``MY_GIT_TOKEN``: GitHub PAT (see GitHub docs for details)
* ``AWS_DEFAULT_REGION``
* ``S3_ENCRYPT_KEY``

We also assume here that the EC2 instance was launched with an IAM role with all
required permissions.

Then, the script can be run via:

        ``source <name of script> <EC2 public IPv4> <path to PEM> <foursight branch>``

.. code-block::

   #!/bin/sh
   
   ec2_address=$1
   pem_file=$2
   foursight_branch=$3
   
   # Configure editors (e.g. Vim here) and git
   scp -r -i $pem_file ~/.vim/vimrc ubuntu@$ec2_address:~/.vimrc
   ssh -i $pem_file ubuntu@$ec2_address 'echo "export EDITOR=vi" >> ~/.bashrc'
   scp -r -i $pem_file ~/.gitconfig ubuntu@$ec2_address:~/.gitconfig
   ssh -i $pem_file ubuntu@$ec2_address "git config --global url.\"https://api:$MY_GIT_TOKEN@github.com/\".insteadOf \"https://github.com/\""
   
   # Configure EC2 with Python, poetry, repos
   ssh -i $pem_file ubuntu@$ec2_address 'bash -s' < <path to local 4dn-cloud-infra>/scripts/local_testing_ec2_setup.sh

   # Add local, configured custom file for the environment
   scp -r -i $pem_file <path to local 4dn-cloud-infra>/custom ubuntu@$ec2_address:~/4dn-cloud-infra/custom
   
   # Switch to foursight branch of interest and create check_setup.json for environment
   ssh -i $pem_file ubuntu@$ec2_address "cd foursight-cgap; git checkout $foursight_branch"
   ssh -i $pem_file ubuntu@$ec2_address "cd 4dn-cloud-infra; poetry run resolve-foursight-checks"
   
   # Provide required environmental variables
   ssh -i $pem_file ubuntu@$ec2_address "sed -i \"1i export S3_ENCRYPT_KEY=$S3_ENCRYPT_KEY\" .bashrc"
   ssh -i $pem_file ubuntu@$ec2_address "sed -i \"1i export AWS_DEFAULT_REGION=$AWS_DEFAULT_REGION\" .bashrc"
   
   # Launch Jupyter notebook on port 8888 on EC2
   ssh -i $pem_file ubuntu@$ec2_address "cd 4dn-cloud-infra; python -m notebook --no-browser --port=8888"
