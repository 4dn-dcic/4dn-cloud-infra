import pytest
from troposphere import Template

from src.constants import Settings
from src.names import Names
from src.parts.srce_datastore import C4SRCEDatastore

ENV = 'smaht-test-srce'
RETAINED_TYPES = ('AWS::RDS::DBInstance', 'AWS::OpenSearchService::Domain', 'AWS::S3::Bucket', 'AWS::KMS::Key')
PRODUCTION = {Settings.RDS_RETENTION_POLICY: 'Snapshot', Settings.ES_RETENTION_POLICY: 'Retain',
              Settings.S3_RETENTION_POLICY: 'Retain'}


def _datastore(synthesis_config, extra=None):
    from src.part import C4Account, C4Tags
    synthesis_config(kind='smaht', deployment='blue/green', extra={Settings.ENV_NAME: ENV, **(extra or {})})
    part = C4SRCEDatastore(name=Names.srce_datastore_stack_name_object(ENV), tags=C4Tags(),
                           account=C4Account(account_number='123456789012', creds_file='/dev/null'))
    return part.build_template(Template()).to_dict()


def _of_type(template, resource_type):
    return {k: v for k, v in template['Resources'].items() if v['Type'] == resource_type}


def test_no_retention_attributes_by_default(synthesis_config):
    template = _datastore(synthesis_config)
    for resource in template['Resources'].values():
        assert 'DeletionPolicy' not in resource and 'UpdateReplacePolicy' not in resource


def test_configured_retention_is_applied_to_both_attributes(synthesis_config):
    default = _datastore(synthesis_config)
    template = _datastore(synthesis_config, PRODUCTION)
    expected = {'AWS::RDS::DBInstance': (1, 'Snapshot'), 'AWS::OpenSearchService::Domain': (2, 'Retain'),
                'AWS::S3::Bucket': (10, 'Retain'), 'AWS::KMS::Key': (1, 'Retain')}
    for resource_type, (count, policy) in expected.items():
        resources = _of_type(template, resource_type)
        assert len(resources) == count, resource_type
        for resource in resources.values():
            assert (resource['DeletionPolicy'], resource['UpdateReplacePolicy']) == (policy, policy)
    # Nothing else changes: same resources, same properties, no other resource gains a policy.
    assert set(template['Resources']) == set(default['Resources'])
    for logical_id, resource in template['Resources'].items():
        assert resource['Properties'] == default['Resources'][logical_id]['Properties']
        if resource['Type'] not in RETAINED_TYPES:
            assert resource == default['Resources'][logical_id]


@pytest.mark.parametrize('setting, value', [(Settings.RDS_RETENTION_POLICY, 'Keep'),
                                            (Settings.ES_RETENTION_POLICY, 'Snapshot'),
                                            (Settings.S3_RETENTION_POLICY, 'Snapshot'),
                                            (Settings.ES_PRIVATE_SUBNET, 'Z')])
def test_invalid_retention_policy_is_rejected(synthesis_config, setting, value):
    with pytest.raises(ValueError, match=setting):
        _datastore(synthesis_config, {setting: value})


def _domain_subnets(template):
    return [domain['Properties']['VPCOptions']['SubnetIds']
            for domain in _of_type(template, 'AWS::OpenSearchService::Domain').values()]


def test_opensearch_subnet_defaults_to_a_and_is_selectable(synthesis_config):
    default = _datastore(synthesis_config)
    assert all(str(subnets).count('PrivateSubnetA') == 1 for subnets in _domain_subnets(default))
    template = _datastore(synthesis_config, {Settings.ES_PRIVATE_SUBNET: 'B'})
    subnets = _domain_subnets(template)
    assert len(subnets) == 2
    assert all(len(ids) == 1 and 'PrivateSubnetB' in str(ids) and 'PrivateSubnetA' not in str(ids)
               for ids in subnets)
    # Only the domains' subnet changes; the RDS subnet group keeps both subnets.
    for logical_id, resource in template['Resources'].items():
        if resource['Type'] != 'AWS::OpenSearchService::Domain':
            assert resource == default['Resources'][logical_id]
