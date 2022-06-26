import io
import mock
import os
import tempfile
from contextlib import contextmanager
from dcicutils.qa_utils import (printed_output as mock_print, MockBoto3, MockBoto3SecretsManager, MockBoto3Session, MockBoto3Sts)
from src.auto.utils import aws_context
from src.auto.utils import aws


def test_setup_remaining_secrets() -> None:
    # Not yet implemented.
    pass
