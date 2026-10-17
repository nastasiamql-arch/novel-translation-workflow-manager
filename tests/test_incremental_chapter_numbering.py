"""Paste one chapter at a time: never change a previously verified prefix."""
import hashlib
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from novel_workflow.chapter_numbering import scan_chapters
from novel_workflow.incremental_chapter_numbering import (
    automatic_append_plan, verified_prefix_from_history,
)
from novel_workflow.models import StepFile
from novel_workflow.workspace_window import MainWindow
from novel_workflow.chapter_numbering_dialog import ChapterNumberDialog
from test_release_36 import setup_profile


def test_verified_prefix_corrects_only_newly_appended_chapters():
    prefix = "第六百三十一章 第一回\n保留中文，第三百章只是正文。\n"
    raw = prefix + "\n第六百四十七章 第二回\n原文\n"
    result, changes = automatic_append_plan(raw, 631, prefix, 646)
    assert result.startswith(prefix)
    assert result == raw.replace("第六百四十七章", "第六百三十二章")
    assert changes == [(4, 647, 632)]
    triple = result + "\n第六百四十八章 第三回\n新故事"
    further, changed = automatic_append_plan(triple, 631, result, 647)
    assert further.startswith(result)
    assert [h.number for h in scan_chapters(further)] == [631, 632, 633]
    assert changed == [(7, 648, 633)]


@pytest.mark.parametrize("new_raw", ["第649章 错过一章\n", "第645章 倒退\n", "第647章 二\n第649章 四\n", "第廿章 特殊\n"])
def test_incremental_renumber_refuses_gaps_and_unsupported_headings(new_raw):
    prefix = "第631章 第一\n正文\n"
    with pytest.raises(ValueError):
        automatic_append_plan(prefix + new_raw, 631, prefix, 646)


def test_incremental_renumber_requires_exact_previous_story_and_original_number():
    prior = "第631章 第一\n正文\n"
    with pytest.raises(ValueError):
        automatic_append_plan(prior + "\n第647章 第二", 631, prior)
    with pytest.raises(ValueError):
        automatic_append_plan(prior.replace("正文", "改动") + "\n第647章 第二", 631, prior, 646)
    with pytest.raises(ValueError):
        automatic_append_plan(prior.rstrip("\n") + "第647章 第二", 631, prior, 646)
    with pytest.raises(ValueError):
        automatic_append_plan(prior + "\n第647章 第二", 631, prior, 645)


def _window(tmp_path, *, fix=True):
    repo, profile, _ = setup_profile(tmp_path)
    root = repo.profile_dir(profile.id) / "source"
    root.mkdir(exist_ok=True)
    source = root / "SEG.txt"
    source.write_text("第646章 起源\n汉字未修改\n", encoding="utf-8")
    translator = root / "SEGTranslator.txt"
    translator.write_text("บทที่ 630\nงานแปล", encoding="utf-8")
    profile.working_files = [StepFile(path="source/SEGTranslator.txt")]
    profile.auto_review_enabled = True
    profile.auto_chapter_number_mode = "fix" if fix else "check"
    repo.save_profile(profile)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.select_profile(next(i for i, value in enumerate(window.ps_list) if value.id == profile.id))
    ws = window.workspaces[profile.id]
    editor = ws.editor.open_file(source)
    ws.editor.tabs.setCurrentWidget(editor)
    messages = []
    window.show_submit_toast = messages.append
    return repo, profile, window, ws, editor, source, translator, messages


def _close(window):
    window._close_export_reminder_accepted = True
    window.close()


def test_three_separate_pastes_auto_renumber_and_persist_verified_history(tmp_path):
    repo, profile, window, ws, editor, source, translator, messages = _window(tmp_path)
    translator_before = translator.read_bytes()
    # The first paste is deliberately edited so save triggers the hook.
    editor.setPlainText("第646章 起源\n汉字未修改\n")
    # Last saved text is identical, so emulate a genuine paste by changing the body.
    editor.setPlainText("第646章 起源\n汉字未修改，第一节。\n")
    assert ws.editor.save_editor(editor, quiet=True)
    ws.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert [h.number for h in scan_chapters(source.read_text(encoding="utf-8"))] == [631]
    previous = source.read_text(encoding="utf-8")
    for raw, expected in ((647, [631, 632]), (648, [631, 632, 633])):
        editor.setPlainText(editor.toPlainText() + f"\n第{raw}章 新章{raw}\n本章内容绝不合并。\n")
        assert ws.editor.save_editor(editor, quiet=True)
        ws.auto_chapter_review_timer.stop()
        window._run_auto_chapter_review(profile.id)
        saved = source.read_text(encoding="utf-8")
        assert saved.startswith(previous)
        assert [h.number for h in scan_chapters(saved)] == expected
        assert f"本章内容绝不合并。" in saved
        previous = saved
    assert translator.read_bytes() == translator_before
    hist = json.loads((repo.profile_dir(profile.id) / "chapter_numbering" / "history.json").read_text(encoding="utf-8"))
    assert len(hist["events"]) == 3
    assert [e["changes"][-1]["original"] for e in hist["events"]] == [646, 647, 648]
    assert [e["changes"][-1]["corrected"] for e in hist["events"]] == [631, 632, 633]
    assert verified_prefix_from_history(repo.profile_dir(profile.id), profile.id, source,
                                       previous, 631) == (previous, 648)
    _close(window)


def test_append_gap_preserves_existing_file_and_backup_history(tmp_path):
    repo, profile, window, ws, editor, source, translator, messages = _window(tmp_path)
    editor.setPlainText("第646章 第一章\n本章内容。\n")
    assert ws.editor.save_editor(editor, quiet=True)
    ws.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    first = source.read_text(encoding="utf-8")
    editor.setPlainText(first + "\n第649章 可能有缺章\n内容")
    assert ws.editor.save_editor(editor, quiet=True)
    ws.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert source.read_text(encoding="utf-8").endswith("第649章 可能有缺章\n内容")
    assert any("ไม่ได้แก้เลขบท" in msg for msg in messages)
    _close(window)


def test_manual_mode_reminds_and_does_not_edit_until_user_confirms(tmp_path, monkeypatch):
    repo, profile, window, ws, editor, source, translator, messages = _window(tmp_path, fix=False)
    editor.setPlainText("第646章 起源\n原文正文\n")
    assert ws.editor.save_editor(editor, quiet=True)
    assert not getattr(ws, "auto_chapter_review_timer", None)
    assert "รอตรวจ" in ws.chapter_number_button.text()
    assert str(source.resolve()) in next(p for p in repo.list_profiles() if p.id == profile.id).chapter_number_pending_files
    original = source.read_bytes()
    # Dismissing the dialog is not an acknowledgement.
    monkeypatch.setattr(ChapterNumberDialog, "exec", lambda self: QDialog.Rejected)
    ws.inspect_chapter_numbers()
    assert "รอตรวจ" in ws.chapter_number_button.text()
    monkeypatch.setattr(ChapterNumberDialog, "exec", lambda self: QDialog.Accepted)
    ws.inspect_chapter_numbers()
    assert ws.chapter_number_button.text() == "ตรวจเลขบท"
    assert not next(p for p in repo.list_profiles() if p.id == profile.id).chapter_number_pending_files
    assert source.read_bytes() == original
    _close(window)
