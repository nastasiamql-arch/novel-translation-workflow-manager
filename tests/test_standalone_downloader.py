"""Independent downloader contract: no translation profile required."""
import json
from pathlib import Path

import pytest

from novel_workflow.downloader.models import BookInfo, ChapterContent, ChapterInfo
from novel_workflow.downloader.registry import SourceRegistry
from novel_workflow.downloader.standalone_service import (
    RateBudget, StandaloneDownloadService, cleaned_raw,
)
from novel_workflow.downloader.standalone_storage import DownloaderRepository


class Source:
    id = "fake"
    name = "Fixture Source"
    domains = ("example.test",)

    def __init__(self):
        self.calls = []

    def can_handle(self, url):
        return url.startswith("https://example.test/book/")

    def get_book(self, url):
        return BookInfo("fake", "novel", url, "小说")

    def get_chapters(self, book):
        return [ChapterInfo(str(i), i, f"第{i}章 测试", f"{book.url}/{i}") for i in range(1, 4)]

    def get_chapter(self, chapter, mode="raw_zh"):
        self.calls.append(chapter.index)
        return ChapterContent(chapter.remote_id, chapter.index, chapter.title,
                              f"第{chapter.index}章 测试\n\n"
                              "这是完整的中文原文段落，保证内容不是英文机器翻译。\n"
                              "第二段原文内容仍然保持换行。")


def prepare(tmp_path):
    store = DownloaderRepository(tmp_path / "NovelWorkflow" / "downloader")
    source = Source()
    svc = StandaloneDownloadService(store, SourceRegistry([source]))
    book, chapters = svc.inspect("https://example.test/book/novel")
    entry = store.save_book(book, tmp_path / "TXT")
    return store, source, svc, entry


def test_separate_and_combined_resume_without_second_fetch(tmp_path, monkeypatch):
    monkeypatch.setattr(RateBudget, "wait", lambda self, cancel=None: None)
    store, source, svc, entry = prepare(tmp_path)
    first = svc.download_range(entry["id"], 1, 3, mode="both")
    assert first.downloaded == 3 and first.failed == 0
    assert source.calls == [1, 2, 3]
    chapter_dir = tmp_path / "TXT" / "Chapters"
    assert [p.name for p in sorted(chapter_dir.glob("*.txt"))] == [
        "0001.txt", "0002.txt", "0003.txt"]
    assert (tmp_path / "TXT" / "Novel_All.txt").read_text(encoding="utf-8").count("第二段") == 3
    source.calls.clear()
    second = svc.download_range(entry["id"], 1, 3, mode="both")
    assert source.calls == [] and second.skipped == 3 and second.failed == 0
    assert not (tmp_path / "NovelWorkflow" / "profiles").exists()
    assert store.list_books()[0]["source_id"] == "fake"


def test_combined_only_has_no_chapter_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(RateBudget, "wait", lambda self, cancel=None: None)
    store, source, svc, entry = prepare(tmp_path)
    assert svc.download_range(entry["id"], 1, 2, mode="combined").failed == 0
    assert not (tmp_path / "TXT" / "Chapters").exists()
    assert (tmp_path / "TXT" / "Novel_All.txt").is_file()


def test_existing_user_txt_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(RateBudget, "wait", lambda self, cancel=None: None)
    store, source, svc, entry = prepare(tmp_path)
    target = tmp_path / "TXT" / "Chapters" / "0001.txt"
    target.parent.mkdir(parents=True)
    target.write_text("MY EDIT", encoding="utf-8")
    result = svc.download_range(entry["id"], 1, 1, mode="separate")
    assert result.failed == 1
    assert target.read_text(encoding="utf-8") == "MY EDIT"


def test_no_profile_folder_can_be_selected(tmp_path):
    store = DownloaderRepository(tmp_path / "NovelWorkflow" / "downloader")
    with pytest.raises(ValueError, match="translation"):
        store.save_book(BookInfo("fake", "a", "https://example.test/book/a", "A"),
                        tmp_path / "NovelWorkflow" / "profiles" / "abc")


def test_raw_footer_removed_without_losing_chinese_paragraphs():
    chapter = ChapterInfo("123", 30, "第30章 时间飞逝")
    text = ("第30章 时间飞逝\n\n这是一段非常完整的原文内容。\n第二段还在。\n\n"
            "TomatoMTL – Advanced MTL Reading Assist Tool\n"
            "URL: https://tomatomtl.com/book/7367710691010022462/123")
    cleaned = cleaned_raw(text, chapter)
    assert cleaned.startswith("第30章 时间飞逝\n\n")
    assert "第二段还在。" in cleaned
    assert "Advanced MTL" not in cleaned
    with pytest.raises(ValueError):
        cleaned_raw("Error: Failed to fetch", chapter)


def test_request_budget_persists_across_instances(tmp_path):
    store = DownloaderRepository(tmp_path / "Downloader")
    limiter = RateBudget(store, delay=10, clock=lambda: 10000)
    limiter.wait()
    attempts = json.loads(store.limits_path.read_text())["attempts"]
    assert attempts == [10000]
    assert store.root.joinpath("books").exists() is False
