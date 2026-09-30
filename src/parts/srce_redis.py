from .redis import C4Redis
from .srce_network import C4SRCEDBNetworkExports


class C4SRCERedis(C4Redis):
    """
    SRCE variant of C4Redis. Deploys the Redis replication group and subnet group inside
    the IT-provided Database VPC by swapping in C4SRCEDBNetworkExports.

    Redis is co-located with RDS/OpenSearch in the Database VPC so that data-tier traffic
    stays within that VPC and does not cross VPC boundaries unnecessarily.
    All cluster configuration logic is inherited from C4Redis unchanged.
    """
    NETWORK_EXPORTS = C4SRCEDBNetworkExports()

    STACK_NAME_TOKEN = 'srce-redis'
    STACK_TITLE_TOKEN = 'SRCERedis'
