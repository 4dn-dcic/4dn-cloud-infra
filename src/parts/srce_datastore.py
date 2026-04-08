from .datastore import C4Datastore
from .srce_network import C4SRCEDBNetworkExports


class C4SRCEDatastore(C4Datastore):
    """
    SRCE variant of C4Datastore. Creates RDS, OpenSearch, S3, and SQS resources
    inside the IT-provided Database VPC by swapping in C4SRCEDBNetworkExports.

    C4SRCEDBNetworkExports uses 'DBNetworkStackNameParameter' as its reference key,
    so the generated template will look up subnet and security group IDs from the
    'srce-network-db' CloudFormation stack rather than the standard network stack.
    All resource creation logic is inherited from C4Datastore unchanged.
    """
    NETWORK_EXPORTS = C4SRCEDBNetworkExports()

    STACK_NAME_TOKEN = 'srce-datastore'
    STACK_TITLE_TOKEN = 'SRCEDatastore'
