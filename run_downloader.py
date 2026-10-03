import os
import sys
from pathlib import Path


_dll_directory_handles = []
_preloaded_qt_dlls = []


def _prepare_bundled_qt_dlls():
    global _preloaded_qt_dlls
    if not getattr(sys, "frozen", False) or not hasattr(sys, "_MEIPASS"):
        return
    root = Path(sys._MEIPASS)
    if hasattr(os, "add_dll_directory"):
        _dll_directory_handles.append(os.add_dll_directory(str(root)))
    for directory in (root / "PySide6", root / "shiboken6"):
        if not directory.is_dir():
            continue
        if hasattr(os, "add_dll_directory"):
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    os.environ["PATH"] = str(root) + os.pathsep + os.environ.get("PATH", "")
    core = root / "PySide6" / "Qt6Core.dll"
    if core.is_file():
        import ctypes

        for dependency in (root / "icuuc.dll", root / "icuin.dll"):
            if dependency.is_file():
                _preloaded_qt_dlls.append(ctypes.WinDLL(str(dependency), winmode=0x8))
        # Search beside this Qt DLL and the bundled paths, avoiding unrelated
        # Qt/ICU DLLs from the user's PATH.
        _preloaded_qt_dlls.append(ctypes.WinDLL(str(core), winmode=0x8))


def _check_packaged_qt_runtime():
    try:
        from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401
        import shiboken6
        from importlib.metadata import version
        shiboken6.__path__.insert(0, str(Path(sys._MEIPASS) / "shiboken6"))
        from novel_workflow import __version__
        if __version__ != version("novelworkflow") or __version__ == "0+unknown":
            raise RuntimeError("Packaged Novel Downloader version metadata is unavailable")
    except Exception as exc:
        if sys.stderr is not None:
            sys.stderr.write(f"Packaged Qt runtime check failed: {exc}\n")
        return 1
    return 0


_prepare_bundled_qt_dlls()

if __name__ == "__main__":
    if "--check-runtime" in sys.argv[1:]:
        raise SystemExit(_check_packaged_qt_runtime())
    from novel_workflow.downloader_main import main

    raise SystemExit(main())
