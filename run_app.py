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
    # Prefer this bundle's Qt and shiboken DLLs. Do not add the bundle root:
    # PyInstaller can collect unrelated ICU DLLs from the build machine's PATH
    # there, which can shadow the compatible ICU runtime provided by Windows.
    for directory in (bundle_root / "PySide6", bundle_root / "shiboken6"):
        if not directory.is_dir():
            continue
        if hasattr(os, "add_dll_directory"):
            _dll_directory_handles.append(os.add_dll_directory(str(directory)))
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")

    # Keep the bundle root on PATH for native libraries that still consult it.
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
        from novel_workflow import __version__

        if __version__ == "0+unknown":
            raise RuntimeError("Packaged NovelWorkflow build version is unavailable")
        if "--expected-version" in sys.argv:
            expected = sys.argv[sys.argv.index("--expected-version") + 1]
            if __version__ != expected:
                raise RuntimeError(f"Expected v{expected}, running v{__version__}")
        if '--check-recycle-bin' in sys.argv:
            import tempfile
            from novel_workflow.recycle_bin import recycle_snapshot
            with tempfile.TemporaryDirectory(prefix='Palantir-Recycle-Probe-') as folder:
                snapshot = Path(folder) / 'Snapshot'; snapshot.mkdir()
                (snapshot / 'payload.txt').write_bytes(b'packaged recycle probe')
                destination = recycle_snapshot(snapshot)
                if (destination / 'payload.txt').read_bytes() != b'packaged recycle probe':
                    raise RuntimeError('Packaged Recycle Bin payload verification failed')
        if '--history-profile' in sys.argv:
            # Optional, read-only installed-runtime probe used by upgrade CI.
            import json
            from novel_workflow.models import NovelProfile
            from novel_workflow.storage import ProjectRepository
            from novel_workflow.services import AssemblyService
            from novel_workflow.polish_history import PolishHistory
            path = Path(sys.argv[sys.argv.index('--history-profile') + 1])
            profile = NovelProfile.from_dict(json.loads(path.read_text(encoding='utf-8-sig')))
            repo = ProjectRepository(path.parent.parent.parent)
            history = PolishHistory(repo, AssemblyService(repo)).list(profile)
            if not history or any(snapshot.error for snapshot in history):
                raise RuntimeError('Installed runtime cannot verify preserved Polish History')
        if '--completion-profile' in sys.argv:
            import json
            from novel_workflow.storage import ProjectRepository
            from novel_workflow.translation_progress import completed_chapter_count
            path = Path(sys.argv[sys.argv.index('--completion-profile') + 1])
            before = json.loads(path.read_text(encoding='utf-8-sig'))
            repo = ProjectRepository(path.parent.parent.parent)
            profile = next(p for p in repo.list_profiles() if p.id == before['id'])
            if profile.translation_daily_activity != before.get('translation_daily_activity', {}):
                raise RuntimeError('Legacy Context statistics changed during upgrade')
            if profile.translator_export_events != before.get('translator_export_events', []):
                raise RuntimeError('Upgrade invented or removed Translator Export events')
            if not before.get('translator_export_events') and completed_chapter_count(profile):
                raise RuntimeError('Upgrade counted legacy Context chapters as confirmed exports')
            if profile.translation_progress_version != 2:
                raise RuntimeError('Completion progress migration did not finish')
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
