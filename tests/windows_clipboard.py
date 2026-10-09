"""Verify the real Windows Explorer CF_HDROP clipboard format, outside offscreen Qt."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import zipfile
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QMimeData, QUrl
from novel_workflow.models import NovelProfile, WorkflowStep, StepFile
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.workflow_archive import create_workflow_archive


def main():
    app = QApplication([])
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    with tempfile.TemporaryDirectory() as directory:
        repo = ProjectRepository(Path(directory))
        profile = NovelProfile()
        repo.save_profile(profile)
        source = repo.profile_dir(profile.id) / 'source' / '中文 ไทย.txt'
        source.write_text('ไทย\n中文\n日本\nEnglish', encoding='utf-8')
        step = WorkflowStep(files=[StepFile(path='source/' + source.name, enabled=False)])
        archive = create_workflow_archive(repo, AssemblyService(repo), profile, [step])
        for path in (source, archive):
            data = QMimeData()
            data.setUrls([QUrl.fromLocalFile(str(path))])
            app.clipboard().setMimeData(data)
            app.processEvents()
            assert user32.OpenClipboard(None)
            try:
                handle = user32.GetClipboardData(15)  # CF_HDROP consumed by Explorer.
                assert handle
                assert shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0) == 1
                length = shell32.DragQueryFileW(handle, 0, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, 0, buffer, length + 1)
                assert Path(buffer.value).resolve() == path.resolve()
            finally:
                user32.CloseClipboard()
        with zipfile.ZipFile(archive) as content:
            assert content.read(content.namelist()[0]) == source.read_bytes()
        app.clipboard().clear()
    print('Windows CF_HDROP PASS: ordinary files, ZIP and Unicode paths are Explorer-compatible.')


if __name__ == '__main__':
    main()
