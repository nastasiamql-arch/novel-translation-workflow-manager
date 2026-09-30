"""Novel Translation Workflow Manager."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("novelworkflow")
except PackageNotFoundError:
    __version__ = "0+unknown"
