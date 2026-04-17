from troposphere import Template

from .datastore import C4Datastore
from .srce_network import C4SRCEDBNetworkExports


# The IAM stack uses SHARING='ecosystem' and is shared across all environments in the account.
# With the default ecosystem qualifier 'main', it is always named c4-iam-main-stack.
SRCE_IAM_STACK_NAME = 'c4-iam-main-stack'


class C4SRCEDatastore(C4Datastore):
    """
    SRCE variant of C4Datastore. Creates RDS, OpenSearch, S3, and SQS resources
    inside the IT-provided Database VPC by swapping in C4SRCEDBNetworkExports.

    C4SRCEDBNetworkExports uses 'DBNetworkStackNameParameter' as its reference key,
    so the generated template will look up subnet and security group IDs from the
    'srce-network-db' CloudFormation stack rather than the standard network stack.

    The IAM stack (c4-iam-main-stack) is ecosystem-scoped and shared across all
    environments in the account. Its name is set as the Default for IAMStackNameParameter
    so deployments resolve correctly without relying on ecosystem config resolution.
    """
    NETWORK_EXPORTS = C4SRCEDBNetworkExports()

    STACK_NAME_TOKEN = 'srce-datastore'
    STACK_TITLE_TOKEN = 'SRCEDatastore'

    def build_template(self, template: Template) -> Template:
        template = super().build_template(template)
        # Patch the IAM stack name parameter to default to the shared main stack.
        # c4-iam-main-stack uses SHARING='ecosystem' and is not env-prefixed, unlike
        # the SRCE datastore/network stacks. This default matches the deployed stack.
        iam_param_key = self.IAM_EXPORTS.reference_param_key
        if iam_param_key in template.parameters:
            template.parameters[iam_param_key].Default = SRCE_IAM_STACK_NAME
        return template
