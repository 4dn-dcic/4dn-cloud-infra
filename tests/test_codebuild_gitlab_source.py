import pytest

from src.constants import Settings
from src.parts.codebuild import C4CodeBuild

GITLAB = 'https://gitlab.example.org/smaht/smaht-portal'
PORTAL = {'smaht-test-blue', 'smaht-test-green'}


def _projects(synthesis_config, synthesize, extra=None):
    synthesis_config(kind='smaht', deployment='blue/green', extra={Settings.ENV_NAME: 'smaht-test', **(extra or {})})
    template = synthesize(C4CodeBuild)
    projects = {r['Properties']['Name']: r for r in template['Resources'].values()
                if r['Type'] == 'AWS::CodeBuild::Project'}
    return template, projects


def test_default_is_github_everywhere(synthesis_config, synthesize):
    _, projects = _projects(synthesis_config, synthesize)
    assert PORTAL <= set(projects)
    for project in projects.values():
        assert project['Properties']['Source']['Type'] == 'GITHUB'
        assert project['Properties']['Environment']['Image'] == C4CodeBuild.BUILD_IMAGE


def test_gitlab_portal_source_changes_only_the_portal_projects(synthesis_config, synthesize):
    default_template, default = _projects(synthesis_config, synthesize)
    template, projects = _projects(synthesis_config, synthesize, {
        Settings.CODEBUILD_PORTAL_SOURCE_TYPE: 'GITLAB_SELF_MANAGED',
        Settings.CODEBUILD_GITHUB_REPOSITORY_URL: GITLAB,
        Settings.CODEBUILD_PORTAL_BUILD_IMAGE: 'aws/codebuild/standard:8.0',
    })
    for name, project in projects.items():
        props = project['Properties']
        if name in PORTAL:
            assert props['Source'] == {'Location': GITLAB, 'Type': 'GITLAB_SELF_MANAGED', 'GitCloneDepth': 1}
            assert props['Environment']['Image'] == 'aws/codebuild/standard:8.0'
        else:  # pipeline / tibanna builders are untouched
            assert project == default[name]
    # Nothing but the portal projects and the portal build role (connection access) differs.
    changed = {k for k in template['Resources'] if template['Resources'][k] != default_template['Resources'][k]}
    assert 'CodeBuildRoleForSmahtTest' in changed
    changed.remove('CodeBuildRoleForSmahtTest')
    assert {template['Resources'][k]['Properties']['Name'] for k in changed} == PORTAL


def test_invalid_portal_source_type_is_rejected(synthesis_config, synthesize):
    with pytest.raises(ValueError, match=Settings.CODEBUILD_PORTAL_SOURCE_TYPE):
        _projects(synthesis_config, synthesize, {Settings.CODEBUILD_PORTAL_SOURCE_TYPE: 'GITLAB'})


def _role_policies(template):
    return {lid: [p['PolicyName'] for p in r['Properties']['Policies']]
            for lid, r in template['Resources'].items() if r['Type'] == 'AWS::IAM::Role'}


def test_gitlab_adds_connection_access_to_the_portal_role_only(synthesis_config, synthesize):
    default_template, _ = _projects(synthesis_config, synthesize)
    assert all(names == ['CBNetworkPolicy'] for names in _role_policies(default_template).values())
    template, _ = _projects(synthesis_config, synthesize, {
        Settings.CODEBUILD_PORTAL_SOURCE_TYPE: 'GITLAB_SELF_MANAGED', Settings.CODEBUILD_GITHUB_REPOSITORY_URL: GITLAB})
    roles = _role_policies(template)
    portal_role = 'CodeBuildRoleForSmahtTest'
    assert roles[portal_role] == ['CBNetworkPolicy', 'CBCodeConnectionsSourcePolicy']
    assert all(names == ['CBNetworkPolicy'] for lid, names in roles.items() if lid != portal_role)
    policy = template['Resources'][portal_role]['Properties']['Policies'][1]['PolicyDocument']['Statement'][0]
    assert set(policy['Action']) == {f'{svc}:{a}' for svc in ('codeconnections', 'codestar-connections')
                                     for a in ('GetConnection', 'GetConnectionToken', 'UseConnection')}
    assert all('connection/*' in str(r) for r in policy['Resource'])


def test_github_builders_can_be_deferred_with_a_gitlab_portal(synthesis_config, synthesize):
    template, projects = _projects(synthesis_config, synthesize, {
        Settings.CODEBUILD_PORTAL_SOURCE_TYPE: 'GITLAB_SELF_MANAGED', Settings.CODEBUILD_GITHUB_REPOSITORY_URL: GITLAB,
        Settings.CODEBUILD_GITHUB_BUILDERS: 'false'})
    assert set(projects) == PORTAL
    types = {r['Type'] for r in template['Resources'].values()}
    assert 'AWS::CodeBuild::SourceCredential' not in types
    assert list(_role_policies(template)) == ['CodeBuildRoleForSmahtTest']
    assert 'GITHUB' not in str(template) and 'offline-test' not in str(template)


def test_deferring_github_builders_requires_gitlab_portal(synthesis_config, synthesize):
    with pytest.raises(ValueError, match=Settings.CODEBUILD_GITHUB_BUILDERS):
        _projects(synthesis_config, synthesize, {Settings.CODEBUILD_GITHUB_BUILDERS: 'false'})


DHI = {Settings.CODEBUILD_DHI_CREDENTIALS_SECRET: 'dhi-registry-credentials',
       Settings.CODEBUILD_DHI_BASE_IMAGE: 'dhi.io/example/python:3.11-pinned'}


def test_dhi_credentials_map_into_portal_builds_only(synthesis_config, synthesize):
    default_template, default = _projects(synthesis_config, synthesize)
    template, projects = _projects(synthesis_config, synthesize, DHI)
    for name, project in projects.items():
        env = project['Properties']['Environment']['EnvironmentVariables']
        if name in PORTAL:
            assert env[-3:] == [
                {'Name': 'DHI_BASE_IMAGE', 'Value': 'dhi.io/example/python:3.11-pinned'},
                {'Name': 'DHI_USERNAME', 'Type': 'SECRETS_MANAGER', 'Value': 'dhi-registry-credentials:username'},
                {'Name': 'DHI_TOKEN', 'Type': 'SECRETS_MANAGER', 'Value': 'dhi-registry-credentials:token'},
            ]
        else:
            assert project == default[name]
    roles = _role_policies(template)
    assert roles['CodeBuildRoleForSmahtTest'] == ['CBNetworkPolicy', 'CBDhiCredentialsAccess']
    assert all(names == ['CBNetworkPolicy'] for lid, names in roles.items() if lid != 'CodeBuildRoleForSmahtTest')
    statement = template['Resources']['CodeBuildRoleForSmahtTest']['Properties']['Policies'][1][
        'PolicyDocument']['Statement'][0]
    assert statement['Action'] == ['secretsmanager:GetSecretValue', 'secretsmanager:DescribeSecret']
    assert 'dhi-registry-credentials-??????' in str(statement['Resource'])


@pytest.mark.parametrize('key', list(DHI))
def test_dhi_settings_must_be_set_together(synthesis_config, synthesize, key):
    with pytest.raises(ValueError, match='or neither'):
        _projects(synthesis_config, synthesize, {key: DHI[key]})
