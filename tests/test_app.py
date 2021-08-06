from dcicutils.misc_utils import override_environ

with override_environ(FOURSIGHT_PREFIX='dummy-', ENV_NAME='junk'):
    from app import InvalidDeployStage, compute_valid_deploy_stages




def test_compute_valid_deploy_stages():

    with override_environ(FOURSIGHT_PREFIX='dummy-', ENV_NAME='junk'):

        valid_stages = compute_valid_deploy_stages()

        print(valid_stages)

        assert 'test' in valid_stages

        assert len(valid_stages) > 1

#
# def test_invalid_deploy_stage():
#
#     e
#
#     e = InvalidDeployStage()