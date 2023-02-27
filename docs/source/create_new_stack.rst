===================
Creating New Stacks
===================
Steps to add Cloudformation stacks to the deployment
----------------------------------------------------

This covers creating a new Cloudformation stack via troposphere.

Step One: Decide what part or parts compose the stack
-----------------------------------------------------

`C4Stack`s are comprised of parts; each part adds to an overall troposphere stack template. So, first, you need to
implement a part, or parts, that compose the stack template.

To know what resources are available, you should reference the troposphere code and the AWS Cloudformation reference.
Note! Troposphere classes have 1-to-1 correspondence with the Cloudformation reference.

Troposphere: https://github.com/cloudtools/troposphere/tree/master/troposphere

AWS Reference: https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-template-resource-type-ref.html

* To add a new part, create a new file under `src/parts`, and create a class which inherits from `C4Part`.
* This class should implement a `build_template(template: Template) -> Template` method, and use the troposphere
  template object to add troposphere resources.
* These resources should be added as class methods. These class methods should have a docstring that refers to a
  documentation link for this Cloudformation resource, and return either a single troposphere resource or an array of
  resources.

Note! You will need `Export` resources in the event you are trying to support cross-stack resources. This allows you
to make references between stacks.


Step Two: Configure a stack creation function and add to the cli
------------------------------------------------------------------

Now that you have a `C4Part` or `C4Parts`s for a stack, configure a new stack using these part(s).

* Add to an existing collection of stacks in `src/stacks/` Currently, `trial.py` for legacy Beanstalk setup, and
`trial_alpha.py` for alpha-testing ECS stack.
* What you're adding is an instantiation of `C4Stack`, which requires a description, account, tags, name, and a list
  of parts. Use a unique name for this stack, and a list of the part(s) you created earlier.
* Once you've added this instantiation function, add this to the `src/cli.py`. You'll need to import this function, and
  add it to a stack resolver method, currently `resolve_legacy_stack` and `resolve_alpha_stack`.

Once you've added the new troposphere part(s), instantiated a stack from those part(s), and wired the new stack into the
command line, you'll be able to generate a Cloudformation template for your new stack, and upload the change set, with
`poetry run cli provision`.
