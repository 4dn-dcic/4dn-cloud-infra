=================================
Making Changes to Existing Stacks
=================================
Modifying Existing Cloud Resources
----------------------------------

------------------
Troposphere Stacks
------------------

Cloud resource changes to troposphere stacks are described here. These stacks are written in Python using the
troposphere library. Once written, they are used to generate Cloudformation YAML, which is what gets uploaded to the AWS
Cloudformation service.

To modify these stacks:

1. Write a change to the troposphere resource definitions, which are individual methods in the C4Part classes
   in `src/parts`. If you're modifying an existing resource method, use the docstring reference link to view the
   possible configuration options, which match up to the troposphere class structure.
2. Add a link to the AWS Cloudformation doc for this resource to the docstring of your new resource. These can be hard
   to find, and having a link there will be useful when making changes in the future.
3. Check the corresponding `build_template` method and update with your new resource if necessary. These methods take
   a troposphere template object, attach resources, and return the updated template. If your resource is not added here
   it will not be added to the Cloudformation template.
4. Use `poetry run cli provision` to generate Cloudformation YAML from the troposphere specification.
   Validate your template for syntactic accuracy with the `--validate` flag. Upload the change set without executing
   the changes with `--upload_change_set`.
5. Log into the console view of the AWS Cloudformation page to view the change set and execute it on the stack.

---------
Foursight
---------

Foursight stacks are described here. These stacks use the chalice serverless web framework to manage code deploys.
Chalice generates Cloudformation, uploads build artifacts to S3, and updates the AWS Cloudformation service with new
lambda information, including the location of the new build artifact.

