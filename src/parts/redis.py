from troposphere import Ref, Template, Parameter, Output, GetAtt
from troposphere.elasticache import CacheCluster, SubnetGroup, SecurityGroup, SecurityGroupIngress
from dcicutils.cloudformation_utils import camelize

from .network import C4NetworkExports, C4Network
from ..base import ConfigManager
from ..constants import Settings
from ..exports import C4Exports
from ..part import C4Part


class C4RedisExports(C4Exports):
    """ Holds Redis layer exports """
    pass


class C4Redis(C4Part):
    """ Builds the Redis cluster and associated resources """
    STACK_NAME_TOKEN = 'redis'
    STACK_TITLE_TOKEN = 'Redis'
    DEFAULT_ENGINE = 'redis'
    DEFAULT_ENGINE_VERSION = '7.0'
    DEFAULT_NODE_COUNT = 1
    DEFAULT_CACHE_NODE_TYPE = 'cache.t4g.small'
    NETWORK_EXPORTS = C4NetworkExports()

    @staticmethod
    def redis_cluster_name(env_name: str):
        return camelize(f'{env_name}-redis')

    def build_template(self, template: Template) -> Template:
        # Adds Network Stack Parameter
        template.add_parameter(Parameter(
            self.NETWORK_EXPORTS.reference_param_key,
            Description='Name of network stack for network import value references',
            Type='String',
        ))

        # Build Redis Cluster
        template.add_resource(self.build_redis_subnet_group())
        cluster = template.add_resource(self.build_redis_cache_cluster())
        template.add_output(self.output_redis_endpoint(cluster))
        return template

    @staticmethod
    def output_redis_endpoint(cluster: CacheCluster) -> Output:
        """ Outputs the endpoint URL """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return Output(
            f'{camelize(env_name)}RedisCacheClusterEndpoint',
            Value=Ref(cluster),
            Description='Endpoint to connect to Redis'
        )

    def build_redis_subnet_group(self) -> SubnetGroup:
        """ Builds the subnet group for Redis, default us-east-1 """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        return SubnetGroup(
            f'{camelize(env_name)}SubnetGroup',
            Description=f'Subnet group for Redis cache cluster associated with {env_name}',
            SubnetIds=[
                self.NETWORK_EXPORTS.import_value(subnet_key)
                for subnet_key in C4NetworkExports.PRIVATE_SUBNETS[:int(ConfigManager.get_config_setting(
                    Settings.SUBNET_PAIR_COUNT, default=2))]
            ],
            Tags=self.tags.cost_tag_obj(),
        )

    def build_redis_cache_cluster(self) -> CacheCluster:
        """ Builds a Redis cluster in the ElastiCache paradigm """
        env_name = ConfigManager.get_config_setting(Settings.ENV_NAME)
        logical_id = self.name.logical_id(self.redis_cluster_name(env_name))
        return CacheCluster(
            logical_id,
            AutoMinorVersionUpgrade=True,
            ClusterName=logical_id,
            Engine=self.DEFAULT_ENGINE,
            EngineVersion=ConfigManager.get_config_setting(Settings.REDIS_ENGINE_VERSION,
                                                           default=self.DEFAULT_ENGINE_VERSION),
            NumCacheNodes=ConfigManager.get_config_setting(Settings.REDIS_NODE_COUNT,
                                                           default=self.DEFAULT_NODE_COUNT),
            CacheNodeType=ConfigManager.get_config_setting(Settings.REDIS_NODE_TYPE,
                                                           default=self.DEFAULT_CACHE_NODE_TYPE),
            CacheSubnetGroupName=Ref(self.build_redis_subnet_group()),
            VpcSecurityGroupIds=[self.NETWORK_EXPORTS.import_value(C4NetworkExports.APPLICATION_SECURITY_GROUP)],
            Tags=self.tags.cost_tag_obj(),
        )
