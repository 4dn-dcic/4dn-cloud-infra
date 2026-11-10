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
    # Nothing but the portal projects differs.
    changed = {k for k in template['Resources'] if template['Resources'][k] != default_template['Resources'][k]}
    assert {template['Resources'][k]['Properties']['Name'] for k in changed} == PORTAL


def test_invalid_portal_source_type_is_rejected(synthesis_config, synthesize):
    with pytest.raises(ValueError, match=Settings.CODEBUILD_PORTAL_SOURCE_TYPE):
        _projects(synthesis_config, synthesize, {Settings.CODEBUILD_PORTAL_SOURCE_TYPE: 'GITLAB'})
