"""End-to-end paste, per-tab scope, and Translator autosave retry."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from datetime import date

from PySide6.QtWidgets import QApplication
from novel_workflow.chapter_number_reference import matched_translator_path, resolve_translator_reference
from novel_workflow.models import StepFile
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


def prepared(tmp_path, *, translator_number=630, confirmed_export=None):
    repo, profile, _ = setup_profile(tmp_path)
    folder = repo.profile_dir(profile.id) / "source"
    folder.mkdir(exist_ok=True)
    source = folder / "SEG.txt"
    source.write_text("第640章 旧内容\n原文", encoding="utf-8")
    unrelated = folder / "Novel.txt"
    unrelated.write_text("第999章 不要修改\n便签", encoding="utf-8")
    translator = folder / "SEGTranslator.txt"
    translator.write_text(f"บทที่ {translator_number}\nภาษาไทย", encoding="utf-8")
    profile.working_files = [StepFile(path="source/SEGTranslator.txt")]
    profile.auto_review_enabled = True
    profile.auto_chapter_number_mode = "fix"
    if confirmed_export is not None:
        profile.translator_export_events = [{
            "profile_id": profile.id,
            "translator_path": str(translator.resolve()),
            "chapters": [confirmed_export],
            "status": "committed",
            "local_date": date.today().isoformat(),
            "event_id": "fixture-confirmed",
        }]
    repo.save_profile(profile)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    work = window.workspaces[profile.id]
    toast = []
    window.show_submit_toast = toast.append
    return window, repo, profile, work, source, unrelated, translator, toast


def finish(window):
    window._close_export_reminder_accepted = True
    window.close()


def test_only_paired_seg_is_changed_and_novel_tab_is_ignored(tmp_path):
    window, repo, profile, work, source, novel, trans, toast = prepared(tmp_path)
    editor_novel = work.editor.open_file(novel)
    editor_novel.setPlainText("第1000章 不相关的内容\n请保留")
    assert work.editor.save_editor(editor_novel, quiet=True)
    assert not getattr(work, "auto_chapter_review_timer", None)
    assert not toast
    before_novel = novel.read_bytes()
    seg_editor = work.editor.open_file(source)
    seg_editor.setPlainText(
        "第646章 长篇标题\n中文正文\n第647章 后续\n更多文字\n"
    )
    assert work.editor.save_editor(seg_editor, quiet=True)
    assert work.auto_chapter_review_timer.isActive()
    work.auto_chapter_review_timer.stop()
    work.editor.tabs.setCurrentWidget(editor_novel)
    window._run_auto_chapter_review(profile.id)
    assert "第631章 长篇标题" in source.read_text(encoding="utf-8"), toast
    assert "第632章 后续" in source.read_text(encoding="utf-8")
    assert novel.read_bytes() == before_novel
    assert trans.read_text(encoding="utf-8").startswith("บทที่ 630")
    assert any("แก้เลขบท" in message for message in toast)
    finish(window)


def test_save_translator_after_source_paste_resumes_without_second_paste(tmp_path):
    window, repo, profile, work, source, novel, translator, toast = prepared(
        tmp_path, translator_number=625, confirmed_export=630
    )
    trans_tab = work.editor.open_file(translator)
    seg_editor = work.editor.open_file(source)
    # Simulate the Translator being edited in another tab while the source is saved.
    # Switching files normally performs an immediate Auto Save on the old tab.
    trans_tab.setPlainText("บทที่ 630\nแปลไทยเสร็จ")
    assert work.editor._dirty(trans_tab)
    seg_editor.setPlainText("第646章 第一\n原文\n第647章 第二\n原文")
    assert work.editor.save_editor(seg_editor, quiet=True)
    work.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert source.read_text(encoding="utf-8").startswith("第646章")
    assert work.auto_chapter_review_waiting_for == (
        source.resolve(), translator.resolve()
    )
    # Translator saves normally and automatically re-queues the original source.
    assert work.editor.save_editor(trans_tab, quiet=True)
    assert work.auto_chapter_review_waiting_for is None
    assert work.auto_chapter_review_timer.isActive()
    work.auto_chapter_review_timer.stop()
    work.editor.tabs.setCurrentWidget(trans_tab)
    window._run_auto_chapter_review(profile.id)
    final = source.read_text(encoding="utf-8")
    assert "第631章 第一" in final and "第632章 第二" in final
    assert translator.read_text(encoding="utf-8").startswith("บทที่ 630")
    finish(window)


def test_translator_mismatch_still_does_not_guess(tmp_path):
    window, repo, profile, work, source, novel, translator, toast = prepared(
        tmp_path, translator_number=625, confirmed_export=630
    )
    editor = work.editor.open_file(source)
    editor.setPlainText("第646章 第一\n原文")
    assert work.editor.save_editor(editor, quiet=True)
    work.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert source.read_text(encoding="utf-8").startswith("第646章")
    assert any("ไม่ได้แก้เลขบท" in s for s in toast)
    finish(window)


def test_unpaired_generic_novel_txt_never_uses_another_translator(tmp_path):
    window, repo, profile, work, source, novel, translator, toast = prepared(tmp_path)
    assert matched_translator_path(repo, profile.id, novel)[0] is None
    assert resolve_translator_reference(repo, profile.id, novel).start is None
    assert window._auto_original_source_eligible(profile, work, source)
    assert not window._auto_original_source_eligible(profile, work, novel)
    finish(window)
