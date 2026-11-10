import pytest

from src.constants import Settings
from src.parts.srce_redis import C4SRCERedis


def _replication_group(synthesis_config, synthesize, extra=None):
    synthesis_config(kind='smaht', deployment='blue/green',
                     extra={Settings.ENV_NAME: 'smaht-test-srce', **(extra or {})})
    template = synthesize(C4SRCERedis)
    groups = [r for r in template['Resources'].values() if r['Type'] == 'AWS::ElastiCache::ReplicationGroup']
    assert len(groups) == 1
    return template, groups[0]


def test_no_preferred_az_by_default(synthesis_config, synthesize):
    _, group = _replication_group(synthesis_config, synthesize)
    assert 'PreferredCacheClusterAZs' not in group['Properties']


def test_preferred_az_is_the_only_change(synthesis_config, synthesize):
    default, _ = _replication_group(synthesis_config, synthesize)
    template, group = _replication_group(synthesis_config, synthesize, {Settings.REDIS_PREFERRED_AZ: 'us-east-1f'})
    assert group['Properties']['PreferredCacheClusterAZs'] == ['us-east-1f']
    del group['Properties']['PreferredCacheClusterAZs']
    assert template == default


def test_preferred_az_requires_single_node(synthesis_config, synthesize):
    with pytest.raises(ValueError, match=Settings.REDIS_PREFERRED_AZ):
        _replication_group(synthesis_config, synthesize, {Settings.REDIS_PREFERRED_AZ: 'us-east-1f',
                                                          Settings.REDIS_NODE_COUNT: '2'})
