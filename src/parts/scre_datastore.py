from .datastore import C4Datastore
from .scre_network import C4SCRENetworkExports


class C4SCREDatastore(C4Datastore):
    """
    SCRE variant of C4Datastore. Creates RDS, OpenSearch, S3, and SQS resources
    inside an IT-provided VPC by swapping in C4SCRENetworkExports, which resolves
    VPC and subnet IDs from the SCRE network stack outputs (backed by config values)
    rather than a self-managed network stack.

    All resource creation logic is inherited from C4Datastore unchanged.
    """
    NETWORK_EXPORTS = C4SCRENetworkExports()

    STACK_NAME_TOKEN = 'scre-datastore'
    STACK_TITLE_TOKEN = 'SCREDatastore'
