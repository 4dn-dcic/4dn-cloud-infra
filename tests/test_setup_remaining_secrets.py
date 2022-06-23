import io
import json
import mock
import os
import pytest
import re
import stat
import tempfile
from typing import Callable
from contextlib import contextmanager
from dcicutils.qa_utils import printed_output as mock_print
from src.auto.setup_remaining_secrets.cli import main
from src.auto.utils.locations import InfraDirectories, InfraFiles


def test_todo_setup_remaining_secrets() -> None:
    # Not yet implemented.
    pass
