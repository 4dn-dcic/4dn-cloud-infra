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

* Register the stack in `src/stacks/alpha_stacks.py` using the `@register_stack_creator(...)`
  decorator, associating a unique stack name with your implementation class.
* What you're adding is a stack backed by a `C4Part` (or several), which requires a description,
  account, tags, name, and its part(s). Use a unique name for this stack.
* The registered stack is then resolved by `src/cli.py` (see `resolve_alpha_stack` /
  `resolve_4dn_stack`), so `cli provision <name>` can build it — no manual wiring beyond the
  registration is required.

Once you've added the new troposphere part(s), instantiated a stack from those part(s), and wired the new stack into the
command line, you'll be able to generate a Cloudformation template for your new stack, and upload the change set, with
`poetry run cli provision`.
