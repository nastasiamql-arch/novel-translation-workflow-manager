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
    assert "第1章正文" in QApplication.clipboard().text()
    assert "第6章正文" not in QApplication.clipboard().text()
    glossary_button = page.findChild(QPushButton, "txtVocabularyCopyGlossary1Batch1")
    glossary_button.click()
    assert QApplication.clipboard().text() == "人物：小明"
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
    assert page.tabs.currentIndex() == 0
    page.pasted_text.setPlainText(paste + "\n第三章 新章\n第三节")
    assert not page.save_button.isEnabled()
    page.close()
