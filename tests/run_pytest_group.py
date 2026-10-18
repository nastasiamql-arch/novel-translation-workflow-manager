"""Run pytest and exit before Windows Qt's native interpreter finalizer.

PySide6 6.11.2 intermittently crashes (0xC0000005) at Python shutdown after
pytest has already reported passing assertions. Preserve pytest's real status
exactly, flush all captured output, then exit without a second Qt teardown.
This does not hide assertion failures, collection errors or interrupts.
"""
from __future__ import annotations

import os
import sys

import pytest


def main():
    try:
        status = int(pytest.main(sys.argv[1:]))
    except BaseException:
        sys.stdout.flush()
        sys.stderr.flush()
        raise
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(status)


if __name__ == "__main__":
    main()
