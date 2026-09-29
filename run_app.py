import os
import sys
from pathlib import Path


_dll_directory_handles = []
_qt_core_handle = None


def _prepare_bundled_qt_dlls():
    """Prefer this frozen app's Qt DLLs over unrelated copies on PATH."""
    global _qt_core_handle
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return

    bundle_root = Path(sys._MEIPASS)
    for directory in (bundle_root / "PySide6", bundle_root / "shiboken6"):
        if not directory.is_dir():
            continue
        if hasattr(os, "add_dll_directory"):
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")

    # Keep the bundle root on PATH for OpenSSL, but do not add it as a DLL
    # directory: Windows may then pick its ICU DLL ahead of the compatible OS ICU.
    os.environ["PATH"] = str(bundle_root) + os.pathsep + os.environ.get("PATH", "")

    # A system-wide Qt installation can win Windows' DLL lookup before the
    # bundled extension is imported. Load this bundle's QtCore by full path.
    qt_core = bundle_root / "PySide6" / "Qt6Core.dll"
    if qt_core.is_file():
        import ctypes

        _qt_core_handle = ctypes.WinDLL(str(qt_core))


_prepare_bundled_qt_dlls()


def _check_packaged_qt_runtime():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
    except Exception as exc:
        if sys.stderr is not None:
            sys.stderr.write(f"Packaged Qt runtime check failed: {exc}\n")
        return 1
    return 0

if __name__ == "__main__":
    if "--check-runtime" in sys.argv[1:]:
        raise SystemExit(_check_packaged_qt_runtime())

    from novel_workflow.main import main

    raise SystemExit(main())
