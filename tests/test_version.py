import os

from dcicutils.qa_utils import VersionChecker


def test_version_and_changelog():

    class MyVersionChecker(VersionChecker):
        PYPROJECT = os.path.join(os.path.dirname(__file__), "../pyproject.toml")
        CHANGELOG = os.path.join(os.path.dirname(__file__), "../CHANGELOG.rst")

    MyVersionChecker.check_version()
