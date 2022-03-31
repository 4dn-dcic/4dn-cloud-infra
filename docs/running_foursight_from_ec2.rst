===================================
Running Foursight "Locally" via EC2
===================================

To run foursight checks/actions on a deployment environment manually, an EC2 within
the deployment's network must be created and configured appropriately.

Step One: Launch an EC2 within deployment's network
---------------------------------------------------

This can be done manually via the AWS Console or scripted out if desired.
For more details, see `JIRA page <Fill in>`_.

Step Two: Configure EC2 with this repository
____________________________________________

This step can be performed in either of the following manners:

* Copy local repository to EC2 instance via `scp -r -i ...`.

* Clone repository to EC2 instance.

An example script of the latter could resemble:


Step Three: Configure EC2 Python environment
--------------------------------------------


Step Four: Checkout foursight branch of interest
------------------------------------------------


Step Five: Update check_setup.json
----------------------------------


Step Six: Ensure up-to-date AWS variables available
------------------------------------------------------


Step Seven: Run check script
----------------------------


Step Eight: Launch Jupyter notebook and run checks/actions or debug
-------------------------------------------------------------------
