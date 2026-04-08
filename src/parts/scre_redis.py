from .redis import C4Redis
from .scre_network import C4SCRENetworkExports


class C4SCRERedis(C4Redis):
    """
    SCRE variant of C4Redis. Deploys the Redis replication group and subnet group inside
    an IT-provided VPC by swapping in C4SCRENetworkExports so all subnet and security group
    cross-stack references resolve against the SCRE network stack outputs.

    All cluster configuration logic is inherited from C4Redis unchanged.
    """
    NETWORK_EXPORTS = C4SCRENetworkExports()

    STACK_NAME_TOKEN = 'scre-redis'
    STACK_TITLE_TOKEN = 'SCRERedis'
