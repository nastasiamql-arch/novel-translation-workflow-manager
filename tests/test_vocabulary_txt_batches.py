"""Tests for vocabulary TXT batching and explicit paste-to-TXT splitting."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from novel_workflow.models import AppSettings
from novel_workflow.storage import ProjectRepository
from novel_workflow.vocabulary_batches import (
    batch_clipboard_text, existing_chapter_targets, make_chapter_batches,
    parse_pasted_chapters, read_utf8_text, scan_chapter_files,
    split_missing_numbers, write_split_chapters,
)
from novel_workflow.vocabulary_batch_page import TxtVocabularyPage


def test_numbered_txt_batches_order_gaps_and_last_short_group(tmp_path):
    for number in range(1, 19):
        (tmp_path / f"{number:04d} 第一章.txt").write_text(f"第{number}章\n中文 ไทย\n\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("non numbered", encoding="utf-8")
    chapters = scan_chapter_files(tmp_path)
    assert [ch.number for ch in chapters] == list(range(1, 19))
    groups = make_chapter_batches(chapters, 5)
    assert [(g.start, g.end, len(g.chapters)) for g in groups] == [
        (1, 5, 5), (6, 10, 5), (11, 15, 5), (16, 18, 3),
    ]
    assert "第1章\n中文 ไทย\n\n" in batch_clipboard_text(groups[0])
    assert "第6章" not in batch_clipboard_text(groups[0])
    custom = make_chapter_batches(chapters, 3, 7, 12)
    assert [(b.start, b.end) for b in custom] == [(7, 9), (10, 12)]
    (tmp_path / "0003 第一章.txt").unlink()
    groups = make_chapter_batches(scan_chapter_files(tmp_path), 5)
    assert groups[0].missing == (3,)
    assert groups[0].chapters[-1].number == 5


def test_scanning_rejects_duplicate_numbers_bad_encoding_and_missing_directory(tmp_path):
    (tmp_path / "0001.txt").write_bytes(b"\xff")
    (tmp_path / "0001 other.txt").write_text("duplicate", encoding="utf-8")
    with pytest.raises(ValueError, match="ซ้ำ"):
        scan_chapter_files(tmp_path)
    (tmp_path / "0001 other.txt").unlink()
    with pytest.raises(ValueError, match="UTF-8"):
        batch_clipboard_text(make_chapter_batches(scan_chapter_files(tmp_path))[0])
    with pytest.raises(ValueError, match="โฟลเดอร์"):
        scan_chapter_files(tmp_path / "missing")


def test_100_pasted_chapters_preserve_all_original_characters(tmp_path):
    text = "\n" + "".join(
        f"第{i}章 标题{i}\n内容 {i} — 中文 ไทย\n\n\n" for i in range(1, 101)
    )
    segments = parse_pasted_chapters(text)
    assert len(segments) == 100
    assert segments[0].filename == "0001 标题1.txt"
    assert segments[-1].filename == "0100 标题100.txt"
    assert split_missing_numbers(segments) == ()
    assert "".join(segment.text for segment in segments) == text
    result = write_split_chapters(tmp_path, segments)
    assert result.written == 100
    assert result.skipped == 0
    assert (tmp_path / segments[-1].filename).read_text(encoding="utf-8") == segments[-1].text
    assert len(make_chapter_batches(scan_chapter_files(tmp_path), 5)) == 20


def test_pasted_duplicate_reports_the_two_real_heading_lines():
    text = "第1章 前言\n内容\n第3章 干仗\n正文\n第三章 新标题\n正文"
    with pytest.raises(ValueError) as error:
        parse_pasted_chapters(text)
    message = str(error.value)
    assert "0003" in message
    assert "ครั้งแรก บรรทัด 3: 第3章 干仗" in message
    assert "ครั้งที่สอง บรรทัด 5: 第三章 新标题" in message


def test_chapter_only_scanner_ignores_lessons_and_prose_without_losing_text():
    # Actual user regression: 第三节课的上课铃... is a class period, not 第3章.
    lesson = "第三节课的上课铃刚刚打响，教室后门的动静就吸引了全班的目光。"
    original = (
        "第2章 前章\n前章正文\n"
        "第3章 干仗\n本章正文\n" + lesson + "\n"
        "第三節 课堂回忆\n这一段也属于第三章。\n"
        "第4回 尾声\n故事结束\n"
    )
    chapters = parse_pasted_chapters(original)
    assert [chapter.number for chapter in chapters] == [2, 3, 4]
    assert lesson in chapters[1].text
    assert "第三節 课堂回忆" in chapters[1].text
    assert "".join(chapter.text for chapter in chapters) == original


def test_chapter_only_scanner_rejects_prose_looking_like_chapter():
    original = (
        "第3章 干仗\n正文\n"
        "第三章的故事在这一刻才刚刚开始。\n"
        "第3章 " + "很长的叙述" * 40 + "\n"
        "第4章 新的一天\n正文"
    )
    chapters = parse_pasted_chapters(original)
    assert [chapter.number for chapter in chapters] == [3, 4]
    assert "".join(chapter.text for chapter in chapters) == original


def test_real_first_chapter_title_with_full_stop_is_not_mistaken_for_preface():
    title = "第1章 钱在银行，人在天堂。"
    lesson = "第三节课的上课铃刚刚打响，教室后门的动静就吸引了全班的目光。"
    content = title + "\n正文\n第2章 转学生\n正文\n第3章 干仗\n" + lesson + "\n"
    chapters = parse_pasted_chapters(content)
    assert [part.number for part in chapters] == [1, 2, 3]
    assert chapters[0].heading == title
    assert lesson in chapters[2].text
    assert "".join(part.text for part in chapters) == content


def test_punctuated_chinese_heading_requires_explicit_separator():
    text = (
        "第1章 钱在银行，人在天堂。\n正文\n"
        "第一章的故事在这一刻才刚刚开始。\n"
        "第2章：新的起点。\n正文"
    )
    parsed = parse_pasted_chapters(text)
    assert [chapter.number for chapter in parsed] == [1, 2]
    assert "第一章的故事" in parsed[0].text
    assert "".join(chapter.text for chapter in parsed) == text


def test_heading_formats_chinese_numbers_thai_english_and_gaps():
    text = "第一章 起始\n甲\n\n第十二章 中间\n乙\n\nบทที่ 13 ทดสอบ\nค\n\nChapter 14 Last\nD"
    chapters = parse_pasted_chapters(text)
    assert [chapter.number for chapter in chapters] == [1, 12, 13, 14]
    assert len(split_missing_numbers(chapters)) == 10
    assert "".join(chapter.text for chapter in chapters) == text
    assert parse_pasted_chapters("第一百零二章 完\ntext")[0].number == 102
    assert parse_pasted_chapters("第一千零十章 完\ntext")[0].number == 1010
    assert parse_pasted_chapters("第１００章 你好\n世界")[0].number == 100


def test_suspicious_pasted_text_is_not_silently_discarded():
    for content in (
        "前言 非章节内容\n第一章 开始\nx",
        "第一章 开始\ntext\n第一章 又一次\nbad",
        "plain body without chapter headers",
    ):
        with pytest.raises(ValueError):
            parse_pasted_chapters(content)


def test_skip_existing_by_chapter_even_if_title_changed_and_explicit_replacement(tmp_path):
    old = tmp_path / "0001 原来的名字.txt"
    old.write_text("保留我", encoding="utf-8")
    content = "第一章 新标题\n修改了\n\n第二章 第二节\n新内容"
    segments = parse_pasted_chapters(content)
    assert existing_chapter_targets(tmp_path, segments) == (old,)
    first = write_split_chapters(tmp_path, segments, on_existing="skip")
    assert (first.written, first.skipped) == (1, 1)
    assert old.read_text(encoding="utf-8") == "保留我"
    assert not (tmp_path / segments[0].filename).exists()
    assert (tmp_path / segments[1].filename).exists()
    second = write_split_chapters(tmp_path, segments, on_existing="replace")
    assert (second.written, second.skipped) == (2, 0)
    assert old.read_text(encoding="utf-8") == segments[0].text
    assert (second.backup_directory / old.name).read_text(encoding="utf-8") == "保留我"
    assert not (tmp_path / segments[0].filename).exists()


def test_invalid_output_directory_rejected(tmp_path):
    segments = parse_pasted_chapters("第一章 A\nhello")
    with pytest.raises(ValueError, match="โฟลเดอร์"):
        write_split_chapters(tmp_path / "nope", segments)
    with pytest.raises(ValueError, match="ตัวเลือก"):
        write_split_chapters(tmp_path, segments, on_existing="overwrite-all")


def test_gui_copy_only_when_clicked_and_split_only_after_explicit_confirmation(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source"
    source.mkdir()
    for n in range(1, 7):
        (source / f"{n:04d}.txt").write_text(f"第{n}章\n第{n}章正文", encoding="utf-8")
    glossary = tmp_path / "术语.txt"
    glossary.write_text("人物：小明", encoding="utf-8")
    settings = AppSettings()
    persisted = []
    page = TxtVocabularyPage(
        {"folder": str(source), "batch_size": 5, "glossary_1": str(glossary)},
        lambda data: persisted.append(data), source,
    )
    QApplication.clipboard().setText("clipboard sentinel")
    assert page.batch_size.value() == 5
    assert QApplication.clipboard().text() == "clipboard sentinel"
    copy = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert copy is not None
    copy.click()
    mime = QApplication.clipboard().mimeData()
    assert mime.hasUrls()
    pasted_files = [Path(url.toLocalFile()).resolve() for url in mime.urls()]
    assert len(pasted_files) == 6  # five originals + one configured glossary
    assert {p.name for p in pasted_files} == {
        *(f"{n:04d}.txt" for n in range(1, 6)), "术语.txt"
    }
    assert pasted_files[-1].read_text(encoding="utf-8") == "人物：小明"
    assert "คัดลอกแล้ว 6 ไฟล์" in copy.text()
    page.batch_size.setValue(3)
    assert persisted[-1]["batch_size"] == 3
    settings.vocabulary_txt_profiles["novel-one"] = persisted[-1]
    assert "novel-two" not in settings.vocabulary_txt_profiles
    repo = ProjectRepository(tmp_path / "storage")
    repo.save_settings(settings)
    assert repo.load_settings().vocabulary_txt_profiles["novel-one"]["batch_size"] == 3

    paste = "第一章 第一节\n一一一\n\n第二章 第二节\n二二二\n"
    page.pasted_text.setPlainText(paste)
    assert not page.save_button.isEnabled()
    page.preview_button.click()
    assert page.preview_table.rowCount() == 2
    assert page.chapter_preview.toPlainText().startswith("第一章")
    assert page.save_button.isEnabled()
    destination = tmp_path / "split"
    destination.mkdir()
    page.state["destination"] = str(destination)
    page._update_labels()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    page.save_button.click()
    assert (destination / "0001 第一节.txt").read_text(encoding="utf-8").startswith("第一章")
    assert (destination / "0002 第二节.txt").read_text(encoding="utf-8").startswith("第二章")
    assert (source / "0001.txt").read_text(encoding="utf-8").startswith("第1章")
    assert page.tabs.currentIndex() == 1
    assert page.pasted_text.toPlainText() == paste
    assert "แยกไฟล์สำเร็จ" in page.paste_summary.text()
    assert not page.save_button.isEnabled()
    page.pasted_text.setPlainText(paste + "\n第三章 新章\n第三节")
    assert not page.save_button.isEnabled()
    page.close()


def test_split_result_and_source_preview_restore_after_restart(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "storage")
    profile_id = "a" * 32
    destination = tmp_path / "split-output"
    destination.mkdir()
    paste = "第一章 第一节\nเนื้อหาบทหนึ่ง\n\n第二章 第二节\nเนื้อหาบทสอง"
    persisted = {}
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)

    page = TxtVocabularyPage(
        {"destination": str(destination)},
        lambda state: persisted.update(state),
        destination,
        repo=repo,
        profile_id=profile_id,
        draft_reader=lambda: repo.load_batch_draft(profile_id, "vocabulary"),
        draft_writer=lambda text: repo.save_batch_draft(profile_id, "vocabulary", text),
    )
    page.tabs.setCurrentIndex(1)
    page.pasted_text.setPlainText(paste)
    page.preview_paste()
    assert page.save_button.isEnabled()
    page.save_button.click()
    assert repo.load_batch_draft(profile_id, "vocabulary") == paste
    assert persisted["split_input_digest"]
    assert persisted["last_tab"] == 1
    page.close()

    reopened = TxtVocabularyPage(
        persisted,
        lambda state: persisted.update(state),
        destination,
        repo=repo,
        profile_id=profile_id,
        draft_reader=lambda: repo.load_batch_draft(profile_id, "vocabulary"),
        draft_writer=lambda text: repo.save_batch_draft(profile_id, "vocabulary", text),
    )
    app.processEvents()
    assert reopened.tabs.currentIndex() == 1
    assert reopened.pasted_text.toPlainText() == paste
    assert reopened.preview_table.rowCount() == 2
    assert "แยกต้นฉบับนี้แล้ว" in reopened.paste_summary.text()
    assert not reopened.save_button.isEnabled()
    assert (destination / "0001 第一节.txt").is_file()
    assert (destination / "0002 第二节.txt").is_file()
    reopened.close()

    # Existing 6.7.3 settings recorded a successful split but intentionally
    # cleared the draft, so migrate that result without asking the user to run
    # the split operation again.
    legacy = dict(persisted)
    legacy.pop("split_input_digest", None)
    legacy["last_tab"] = 0
    repo.save_batch_draft(profile_id, "vocabulary", "")
    migrated = TxtVocabularyPage(
        legacy,
        lambda state: legacy.update(state),
        destination,
        repo=repo,
        profile_id=profile_id,
        draft_reader=lambda: repo.load_batch_draft(profile_id, "vocabulary"),
        draft_writer=lambda text: repo.save_batch_draft(profile_id, "vocabulary", text),
    )
    app.processEvents()
    assert migrated.tabs.currentIndex() == 1
    assert "แยกไฟล์ครั้งล่าสุดแล้ว" in migrated.paste_summary.text()
    assert "ตรวจไฟล์ในปลายทาง" in migrated.paste_summary.text()
    assert not migrated.save_button.isEnabled()
    migrated.close()

    repo.save_batch_draft(profile_id, "vocabulary", paste)
    (destination / "0002 第二节.txt").unlink()
    missing_output = TxtVocabularyPage(
        persisted,
        lambda state: persisted.update(state),
        destination,
        repo=repo,
        profile_id=profile_id,
        draft_reader=lambda: repo.load_batch_draft(profile_id, "vocabulary"),
        draft_writer=lambda text: repo.save_batch_draft(profile_id, "vocabulary", text),
    )
    app.processEvents()
    assert "ไฟล์ปลายทางหาย" in missing_output.paste_summary.text()
    assert missing_output.save_button.isEnabled()
    missing_output.close()


def test_bulk_1000_chapters_lazy_scroll_search_and_copy_without_jump(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "source"
    source.mkdir()
    for number in range(1, 1001):
        (source / f"{number:04d} 章节.txt").write_text(
            f"第{number}章 中文", encoding="utf-8"
        )
    page = TxtVocabularyPage({"folder": str(source), "batch_size": 5},
                             lambda _state: None, source)
    page.resize(1000, 620)
    page.show()
    app.processEvents()
    assert len(page._groups) == 200
    assert len(page._batch_widgets) == 36  # bounded initial allocation
    assert page.scroll.verticalScrollBar().maximum() > 0
    page.chapter_search.setText("0963")
    page.jump_to_chapter()
    app.processEvents()
    assert len(page._batch_widgets) == 200  # access to late groups on demand
    position = page.scroll.verticalScrollBar().value()
    assert position > 0
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch193")
    assert button is not None
    assert "คัดลอก 5 ไฟล์" in button.text()
    button.click()
    app.processEvents()
    assert page.scroll.verticalScrollBar().value() == position
    urls = QApplication.clipboard().mimeData().urls()
    assert len(urls) == 5
    assert [Path(url.toLocalFile()).stem[:4] for url in urls] == [
        "0961", "0962", "0963", "0964", "0965"
    ]
    detail = page.findChild(QPushButton, "txtVocabularyDetails193")
    assert detail is not None
    assert "ดูรายชื่อไฟล์" in detail.text()
    detail.click()
    app.processEvents()
    assert "ซ่อนรายชื่อไฟล์" in detail.text()
    page.close()


def test_missing_reference_does_not_replace_clipboard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    (tmp_path / "0001.txt").write_text("中文", encoding="utf-8")
    page = TxtVocabularyPage(
        {"folder": str(tmp_path), "glossary_1": str(tmp_path / "missing.txt")},
        lambda _state: None, tmp_path,
    )
    failures = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kw: failures.append(args[2]))
    QApplication.clipboard().setText("original clipboard")
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert button is not None
    button.click()
    assert failures
    assert QApplication.clipboard().text() == "original clipboard"
    page.close()


def test_duplicate_reference_paths_are_copied_only_once(tmp_path):
    app = QApplication.instance() or QApplication([])
    first = tmp_path / "0001.txt"
    first.write_text("中文", encoding="utf-8")
    glossary = tmp_path / "术语.txt"
    glossary.write_text("字典", encoding="utf-8")
    page = TxtVocabularyPage(
        {"folder": str(tmp_path), "glossary_1": str(glossary),
         "glossary_2": str(glossary)},
        lambda _state: None, tmp_path,
    )
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert button is not None
    assert "คัดลอก 2 ไฟล์" in button.text()
    button.click()
    assert len(QApplication.clipboard().mimeData().urls()) == 2
    page.close()
