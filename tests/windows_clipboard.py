"""Verify the real Windows Explorer CF_HDROP clipboard format, outside offscreen Qt."""
import ctypes
from ctypes import wintypes
from pathlib import Path
import tempfile
import time
import zipfile
from PySide6.QtWidgets import QApplication, QPushButton
from novel_workflow.vocabulary_batch_page import TxtVocabularyPage
from PySide6.QtCore import QMimeData, QUrl
from novel_workflow.models import NovelProfile, WorkflowStep, StepFile
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.workflow_archive import create_workflow_archive
from novel_workflow.workspace_editor import EditorTabs
from novel_workflow.polish_history import PolishHistory


def main():
    app = QApplication([])
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    shell32 = ctypes.WinDLL('shell32', use_last_error=True)
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    def open_clipboard():
        # Explorer/clipboard managers can briefly hold the system-wide lock.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if user32.OpenClipboard(None): return True
            app.processEvents(); time.sleep(.01)
        return False
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
    shell32.DragQueryFileW.restype = wintypes.UINT
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GlobalLock.argtypes = [wintypes.HANDLE]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [wintypes.HANDLE]
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
            assert open_clipboard()
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
        profile.main_folder = directory
        profile.context_path = str(source)
        binary = source.parent / 'Disabled.bin'; binary.write_bytes(bytes(range(256)))
        step.files.append(StepFile(path='source/Disabled.bin', enabled=False))
        profile.workflow.steps = [step]
        history = PolishHistory(repo, AssemblyService(repo))
        snapshot = history.create(profile, step, '6-10')
        assert snapshot.manifest['file_count'] == 2
        for zipped in (False, True):
            paths = history.clipboard_paths(profile, snapshot.path, zipped=zipped)
            data = QMimeData(); data.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
            app.clipboard().setMimeData(data); app.processEvents()
            assert open_clipboard()
            try:
                handle = user32.GetClipboardData(15)
                assert handle and shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0) == len(paths)
                for index, path in enumerate(paths):
                    length = shell32.DragQueryFileW(handle, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    shell32.DragQueryFileW(handle, index, buffer, length + 1)
                    assert Path(buffer.value).resolve() == path.resolve()
            finally: user32.CloseClipboard()
        print('Polish History CF_HDROP PASS: verified snapshots and persistent ZIP delivery.')
        # Exercise the actual new TXT vocabulary card, not a handcrafted mimic.
        vocabulary_folder = Path(directory) / 'vocabulary_source'
        vocabulary_folder.mkdir()
        for chapter_number in range(111, 116):
            (vocabulary_folder / f'{chapter_number:04d} 中文标题.txt').write_text(
                f'第{chapter_number}章 正文', encoding='utf-8'
            )
        references = []
        for idx in (1, 2):
            path = Path(directory) / f'词汇{idx}.txt'
            path.write_text(f'人物{idx}\n', encoding='utf-8')
            references.append(path)
        page = TxtVocabularyPage(
            {'folder': str(vocabulary_folder), 'glossary_1': str(references[0]),
             'glossary_2': str(references[1]), 'batch_size': 5},
            lambda _state: None, vocabulary_folder,
        )
        copy_button = page.findChild(QPushButton, 'txtVocabularyCopyBatch1')
        assert copy_button is not None
        copy_button.click()
        app.processEvents()
        expected = {p.resolve() for p in vocabulary_folder.glob('*.txt')} | {p.resolve() for p in references}
        assert len(expected) == 7
        assert open_clipboard()
        try:
            handle = user32.GetClipboardData(15)  # Windows Explorer CF_HDROP
            assert handle
            file_count = shell32.DragQueryFileW(handle, 0xFFFFFFFF, None, 0)
            assert file_count == 7, f'Expected 7 individual files, got {file_count}'
            actual = set()
            for index in range(file_count):
                length = shell32.DragQueryFileW(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(handle, index, buffer, length + 1)
                actual.add(Path(buffer.value).resolve())
            assert actual == expected
        finally:
            user32.CloseClipboard()
        assert all(p.exists() for p in expected)
        page.close()
        print('TXT vocabulary CF_HDROP PASS: 5 Chinese source files + 2 references in one click.')
        vocabulary = '康斯坦丁\tคอนสแตนติน\tชาย\tชื่อเรียกคอนสแตนติน ฟอน นอยรัทในวงประชุมผู้นำนาซี'
        vocabulary += '\n李秀\tซิ่ว\t\t\n\t\t\t'
        glossary = Path(directory) / 'glossary.txt'
        glossary.write_text('', encoding='utf-8')
        tabs = EditorTabs(); editor = tabs.open_file(glossary)
        data = QMimeData(); data.setText(vocabulary)
        data.setHtml('<p>HTML fallback must not replace TSV plain text</p>')
        app.clipboard().setMimeData(data); app.processEvents()
        assert app.clipboard().text() == vocabulary  # Evidence at clipboard input.
        editor.paste(); editor.selectAll(); editor.copy(); app.processEvents()
        assert open_clipboard()
        try:
            handle = user32.GetClipboardData(13)  # CF_UNICODETEXT read by other apps.
            pointer = kernel32.GlobalLock(handle)
            assert pointer
            try:
                native_text = ctypes.wstring_at(pointer).replace('\r\n', '\n')
                assert native_text == vocabulary
                assert native_text.split('\n')[0].count('\t') == 3
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
        assert tabs.save_editor(editor)
        assert EditorTabs().open_file(glossary).toPlainText() == vocabulary
        assert glossary.read_text(encoding='utf-8') == vocabulary
        print('Windows CF_UNICODETEXT PASS: plain/HTML paste, TSV tabs, empty columns, copy/save/reopen.')
        app.clipboard().clear()
    print('Windows CF_HDROP PASS: ordinary files, ZIP and Unicode paths are Explorer-compatible.')


if __name__ == '__main__':
    main()
