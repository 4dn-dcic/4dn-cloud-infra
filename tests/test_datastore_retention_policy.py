import pytest
from troposphere import Template

from src.constants import Settings
from src.names import Names
from src.parts.srce_datastore import C4SRCEDatastore

ENV = 'smaht-test-srce'
RETAINED_TYPES = ('AWS::RDS::DBInstance', 'AWS::OpenSearchService::Domain')


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
    template = _datastore(synthesis_config, {Settings.RDS_RETENTION_POLICY: 'Snapshot',
                                             Settings.ES_RETENTION_POLICY: 'Retain'})
    rds = _of_type(template, 'AWS::RDS::DBInstance')
    domains = _of_type(template, 'AWS::OpenSearchService::Domain')
    assert len(rds) == 1 and len(domains) == 2  # blue and green
    for resource in rds.values():
        assert (resource['DeletionPolicy'], resource['UpdateReplacePolicy']) == ('Snapshot', 'Snapshot')
    for resource in domains.values():
        assert (resource['DeletionPolicy'], resource['UpdateReplacePolicy']) == ('Retain', 'Retain')
    # Nothing else changes: same resources, same properties, no other resource gains a policy.
    assert set(template['Resources']) == set(default['Resources'])
    for logical_id, resource in template['Resources'].items():
        assert resource['Properties'] == default['Resources'][logical_id]['Properties']
        if resource['Type'] not in RETAINED_TYPES:
            assert resource == default['Resources'][logical_id]


@pytest.mark.parametrize('setting, value', [(Settings.RDS_RETENTION_POLICY, 'Keep'),
                                            (Settings.ES_RETENTION_POLICY, 'Snapshot')])
def test_invalid_retention_policy_is_rejected(synthesis_config, setting, value):
    with pytest.raises(ValueError, match=setting):
        _datastore(synthesis_config, {setting: value})
