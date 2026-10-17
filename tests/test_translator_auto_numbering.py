"""Translator-derived chapter-number correction regression tests."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
import json

import pytest
from PySide6.QtWidgets import QApplication
from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.storage import ProjectRepository
from novel_workflow.chapter_numbering import (
    automatic_renumber_plan, format_heading_number, parse_number, preview_renumber
)
from novel_workflow.workspace_window import MainWindow
from test_release_36 import setup_profile


@pytest.mark.parametrize(("old", "number", "result"), [
    ("641", 621, "621"),
    ("６４１", 621, "６２１"),
    ("六百四十一", 621, "六百二十一"),
    ("六百四十一", 620, "六百二十"),
    ("兩百零三", 221, "兩百二十一"),
    ("四百〇一", 402, "四百〇二"),
    ("十", 11, "十一"),
    ("一萬零一", 10002, "一萬零二"),
    ("一亿零一", 100000002, "一亿零二"),
    ("二千零一", 2002, "二千零二"),
])
def test_numeral_format_matches_input(old, number, result):
    assert format_heading_number(number, old) == result
    assert parse_number(result) == number


def test_resequence_chinese_source_without_touching_story_or_layout():
    raw = "第六百四十一章 逆神教老巢\n李玄苍說：『章621是提示』\n\n第六百四十二章 餘波\n　　第三章的文字不应算作章节。\n"
    expected, changed = automatic_renumber_plan(raw, 621)
    assert changed == [(1, 641, 621), (4, 642, 622)]
    assert expected == raw.replace("第六百四十一章", "第六百二十一章").replace(
        "第六百四十二章", "第六百二十二章"
    )
    assert "章621是提示" in expected
    assert automatic_renumber_plan(expected, 621) == (expected, [])
    assert preview_renumber("第６４１章 章名\n故事", {0: 621})[0] == "第６２１章 章名\n故事"


@pytest.mark.parametrize("text", [
    "第641章\n正文\n第643章\n正文",
    "第641章\n正文\n第641章\n正文",
    "第641章\n正文\n第廿章 名称",
    "第641章\n正文\n第???章 名称",
    "第620章\n正文",
    "第0章\n正文",
])
def test_unsafe_source_is_never_auto_resequenced(text):
    with pytest.raises(ValueError):
        automatic_renumber_plan(text, 621)


def make_window(tmp_path, *, source_text="第641章 开端\n原文正文", translator_number=620,
                duplicate=False):
    repo, p, _ = setup_profile(tmp_path)
    folder = repo.profile_dir(p.id) / "source"
    folder.mkdir(exist_ok=True)
    source = folder / "SEG.txt"
    source.write_text("第600章 上次的原文\n旧内容", encoding="utf-8")
    translator = folder / "SEGTranslator.txt"
    translator.write_text(f"บทที่ {translator_number}\nงานแปลไทย", encoding="utf-8")
    p.working_files = [StepFile(path="source/SEGTranslator.txt")]
    if duplicate:
        other = folder / "SEG_Translator.txt"
        other.write_text("บทที่ 888\nข้อมูลอื่น", encoding="utf-8")
        p.working_files.append(StepFile(path="source/SEG_Translator.txt"))
    p.auto_review_enabled = True
    p.auto_chapter_number_mode = "fix"
    repo.save_profile(p)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.select_profile(next(i for i, v in enumerate(window.ps_list) if v.id == p.id))
    workspace = window.workspaces[p.id]
    editor = workspace.editor.open_file(source)
    workspace.editor.tabs.setCurrentWidget(editor)
    messages = []
    window.show_submit_toast = messages.append
    editor.setPlainText(source_text)
    assert workspace.editor.save_editor(editor, quiet=True)
    if duplicate:
        # Two possible Translator files must not silently schedule a correction.
        assert not hasattr(workspace, "auto_chapter_review_timer")
    else:
        assert workspace.auto_chapter_review_timer.isActive()
        workspace.auto_chapter_review_timer.stop()
    return window, repo, p, source, translator, workspace, editor, messages


def close(window):
    window._close_export_reminder_accepted = True
    window.close()


def test_auto_paste_rewrites_source_only_saves_history_and_does_not_loop(tmp_path):
    raw = "第六百四十一章 逆神教老巢\n中文、符号。\n第六百四十二章 下一篇\n段落内容"
    window, repo, p, source, translator, work, editor, messages = make_window(
        tmp_path, source_text=raw
    )
    original_translator = translator.read_bytes()
    window._run_auto_chapter_review(p.id)
    result = source.read_text(encoding="utf-8")
    assert result == raw.replace("第六百四十一章", "第六百二十一章").replace(
        "第六百四十二章", "第六百二十二章"
    )
    assert editor.toPlainText() == result
    assert translator.read_bytes() == original_translator
    events = json.loads((repo.profile_dir(p.id) / "chapter_numbering" / "history.json").read_text(encoding="utf-8"))["events"]
    assert len(events) == 1
    assert events[0]["changes"] == [
        {"line": 1, "original": 641, "corrected": 621},
        {"line": 3, "original": 642, "corrected": 622},
    ]
    saved_backup = repo.profile_dir(p.id) / "chapter_numbering" / events[0]["snapshot"]
    assert json.loads(saved_backup.read_text(encoding="utf-8"))["text"] == raw
    window._run_auto_chapter_review(p.id)
    assert len(json.loads((repo.profile_dir(p.id) / "chapter_numbering" / "history.json").read_text(encoding="utf-8"))["events"]) == 1
    assert any("แก้เลขบท" in message for message in messages)
    close(window)


def test_ambiguous_translator_never_edits_source(tmp_path):
    window, repo, p, source, translator, work, editor, messages = make_window(
        tmp_path, duplicate=True
    )
    unchanged = hashlib.sha256(source.read_bytes()).digest()
    window._run_auto_chapter_review(p.id)
    assert hashlib.sha256(source.read_bytes()).digest() == unchanged
    assert not messages  # Unrelated or ambiguous source never starts auto-review.
    assert not (repo.profile_dir(p.id) / "chapter_numbering" / "history.json").exists()
    close(window)


def test_old_auto_check_setting_migrates_to_non_destructive_mode(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="Legacy")
    profile.auto_review_enabled = True
    repo.save_profile(profile)
    file = repo.profile_dir(profile.id) / "profile.json"
    data = json.loads(file.read_text(encoding="utf-8"))
    data.pop("auto_chapter_number_mode", None)
    file.write_text(json.dumps(data), encoding="utf-8")
    loaded = next(p for p in repo.list_profiles() if p.id == profile.id)
    assert loaded.auto_chapter_number_mode == "check"


def test_per_novel_settings_offer_explicit_auto_fix_choice(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name="Second"); repo.save_profile(second)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(repo)
    window.settings_dialog()
    mode = window.settings_auto_chapter_number_mode
    assert mode.currentData() == "check"
    assert not window.settings_auto_review_enabled.isChecked()
    window.settings_auto_review_enabled.setChecked(True)
    mode.setCurrentIndex(mode.findData("fix"))
    persisted = next(p for p in repo.list_profiles() if p.id == first.id)
    assert persisted.auto_review_enabled and persisted.auto_chapter_number_mode == "fix"
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == second.id))
    assert not window.settings_auto_review_enabled.isChecked()
    assert mode.currentData() == "check"
    assert not next(p for p in repo.list_profiles() if p.id == second.id).auto_review_enabled
    close(window)
