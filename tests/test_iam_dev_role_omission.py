import pytest

from src.constants import Settings
from src.parts.iam import C4IAM

# Role/profile logical ids are chosen by app kind when src.parts.iam is imported, so read them from
# the class rather than hardcoding one app's names.
RUNTIME_RESOURCES = {C4IAM.ROLE_NAME, 'VPCFlowLogRole', C4IAM.INSTANCE_PROFILE_NAME,
                     C4IAM.AUTOSCALING_ROLE_NAME, 'C4IAMMainApplicationS3Federator'}
RUNTIME_OUTPUTS = {'C4IAMMainECSAssumedIAMRole', 'C4IAMMainECSAutoscalingIAMRole', 'C4IAMMainECSS3IAMUser',
                   'C4IAMMainECSInstanceProfile'}
DEV_OUTPUT = 'C4IAMMainECSDevUserRole'


def _iam(synthesis_config, synthesize, extra=None):
    synthesis_config(kind='smaht', deployment='blue/green',
                     extra={Settings.ENV_NAME: 'smaht-test-srce', **(extra or {})})
    return synthesize(C4IAM)


@pytest.mark.parametrize('extra', [None, {Settings.IAM_OMIT_DEV_ROLE: 'False'},
                                   {Settings.IAM_OMIT_DEV_ROLE: 'false'}])
def test_dev_role_kept_by_default(synthesis_config, synthesize, extra):
    template = _iam(synthesis_config, synthesize, extra)
    assert set(template['Resources']) == RUNTIME_RESOURCES | {C4IAM.DEV_ROLE}
    assert set(template['Outputs']) == RUNTIME_OUTPUTS | {DEV_OUTPUT}


@pytest.mark.parametrize('value', ['True', 'true'])
def test_dev_role_omitted_when_opted_in(synthesis_config, synthesize, value):
    default = _iam(synthesis_config, synthesize)
    template = _iam(synthesis_config, synthesize, {Settings.IAM_OMIT_DEV_ROLE: value})
    assert set(template['Resources']) == RUNTIME_RESOURCES
    assert set(template['Outputs']) == RUNTIME_OUTPUTS
    # Everything that remains is exactly what the default stack builds.
    for logical_id in RUNTIME_RESOURCES:
        assert template['Resources'][logical_id] == default['Resources'][logical_id]
    for logical_id in RUNTIME_OUTPUTS:
        assert template['Outputs'][logical_id] == default['Outputs'][logical_id]
    assert C4IAM.DEV_ROLE not in str(template)
    assert 'ECSDevUserRole' not in str(template)
