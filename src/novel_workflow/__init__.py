"""Novel Translation Workflow Manager."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys

if getattr(sys, "frozen", False):
    # Installation upgrades may retain old dist-info directories. Identify the
    # running executable by its bundled build version, never metadata ordering.
    try:
        __version__ = (Path(__file__).parent / "resources" / "app-version.txt").read_text(encoding="utf-8").strip()
    except OSError:
        __version__ = "0+unknown"
else:
    try:
        __version__ = version("novelworkflow")
    except PackageNotFoundError:
        __version__ = "0+unknown"
