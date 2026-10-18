"""Copy immediately after paste must never snapshot a stale chapter number."""
import json
import os
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from novel_workflow.models import StepFile
from test_translator_auto_numbering import make_window, close


def _prepared(tmp_path):
    window, repo, profile, source, translator, workspace, editor, messages = make_window(
        tmp_path, source_text="第646章 初稿\n旧原文\n", translator_number=630
    )
    window.profile.workflow.steps[0].files = [StepFile(path="source/SEG.txt")]
    repo.save_profile(window.profile)
    return window, repo, profile, source, translator, workspace, editor, messages


def _copied_file():
    urls = QApplication.clipboard().mimeData().urls()
    assert len(urls) == 1
    return Path(urls[0].toLocalFile())


def test_copy_step_immediately_after_paste_uses_corrected_source(tmp_path):
    window, repo, profile, source, translator, workspace, editor, messages = _prepared(tmp_path)
    try:
        # No Qt event processing: neither autosave nor review timer has fired.
        editor.setPlainText("第646章 复制前修复\n正文必须保持不变。\n")
        assert workspace.editor._dirty(editor)
        window.copy_step(advance=False)
        assert source.read_text(encoding="utf-8") == "第631章 复制前修复\n正文必须保持不变。\n"
        assert _copied_file().read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
        history = json.loads((repo.profile_dir(profile.id) / "chapter_numbering" / "history.json").read_text(encoding="utf-8"))
        assert history["events"][-1]["changes"] == [
            {"line": 1, "original": 646, "corrected": 631}
        ]
        assert translator.read_text(encoding="utf-8").startswith("บทที่ 630")
    finally:
        close(window)


def test_copy_zip_immediately_after_paste_contains_corrected_source(tmp_path):
    window, repo, profile, source, translator, workspace, editor, messages = _prepared(tmp_path)
    try:
        window.settings.copy_files_as_zip = True
        editor.setPlainText("第646章 复制ZIP前修复\n文字不能修改。\n")
        window.copy_step(advance=False)
        with zipfile.ZipFile(_copied_file()) as archive:
            contents = [archive.read(name).decode("utf-8") for name in archive.namelist()]
        assert len(contents) == 1
        assert contents[0] == source.read_text(encoding="utf-8")
        assert "第631章 复制ZIP前修复" in contents[0]
    finally:
        close(window)


def test_copy_refuses_unverified_source_and_keeps_old_clipboard(tmp_path, monkeypatch):
    window, repo, profile, source, translator, workspace, editor, messages = _prepared(tmp_path)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    try:
        QApplication.clipboard().setText("previous clipboard")
        editor.setPlainText("第646章 第一\n正文\n第648章 缺了一章\n正文")
        window.copy_step(advance=False)
        assert QApplication.clipboard().text() == "previous clipboard"
        assert source.read_text(encoding="utf-8").startswith("第646章 第一")
        assert warnings and "เลขบท" in str(warnings[0])
    finally:
        close(window)


def test_saved_sources_are_queued_separately_not_overwritten(tmp_path):
    window, repo, profile, source, translator, workspace, editor, messages = _prepared(tmp_path)
    try:
        folder = source.parent
        second = folder / "FATE.txt"
        second.write_text("第646章 旧内容\n正文", encoding="utf-8")
        (folder / "FATETranslator.txt").write_text("บทที่ 630\n已翻译", encoding="utf-8")
        editor.setPlainText("第646章 第一本\n正文变化")
        assert workspace.editor.save_editor(editor, quiet=True)
        second_editor = workspace.editor.open_file(second)
        second_editor.setPlainText("第646章 第二本\n正文变化")
        assert workspace.editor.save_editor(second_editor, quiet=True)
        pending = workspace.auto_chapter_review_paths
        assert pending == {source.resolve(), second.resolve()}
        workspace.auto_chapter_review_timer.stop()
        window._drain_auto_chapter_reviews(profile.id)
        assert "第631章 第一本" in source.read_text(encoding="utf-8")
        assert "第631章 第二本" in second.read_text(encoding="utf-8")
        assert pending == set()
    finally:
        close(window)
