import os
import sys
from pathlib import Path


_dll_directory_handles = []


def _prepare_bundled_qt_dlls():
    """Prefer this frozen app's Qt DLLs over unrelated copies on PATH."""
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return

    bundle_root = Path(sys._MEIPASS)
    for directory in (bundle_root / "PySide6", bundle_root):
        if not directory.is_dir():
            continue
        if hasattr(os, "add_dll_directory"):
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


_prepare_bundled_qt_dlls()


def _check_packaged_qt_runtime():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    except Exception as exc:
        sys.stderr.write(f"Packaged Qt runtime check failed: {exc}\n")
        return 1
    return 0

if __name__ == "__main__":
    if "--check-runtime" in sys.argv[1:]:
        raise SystemExit(_check_packaged_qt_runtime())

    from novel_workflow.main import main

    raise SystemExit(main())
