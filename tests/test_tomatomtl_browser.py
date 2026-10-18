"""Visible browser adapter contract; no live website requests in CI."""
import pytest

from novel_workflow.downloader.models import BookInfo, ChapterInfo
from novel_workflow.downloader.sources.tomatomtl_browser import (
    TomatoMTLBrowserSource, chapter_links,
)


def test_catalog_ignores_early_latest_and_duplicate_continue():
    book = BookInfo("tomatomtl", "123", "https://tomatomtl.com/book/123", "小说")
    links = [
        {"href": "https://tomatomtl.com/book/123/999", "title": "第999章 最新"},
        {"href": "https://tomatomtl.com/book/123/101", "title": "第1章 开始"},
        {"href": "https://tomatomtl.com/book/123/102", "title": "第2章 继续"},
        {"href": "https://tomatomtl.com/book/123/102", "title": "第2章 继续"},
        {"href": "https://evil.test/book/123/103", "title": "第3章 恶意"},
        {"href": "https://tomatomtl.com/book/123/glossary", "title": "词汇"},
    ]
    result = chapter_links(book, links)
    assert [(x.remote_id, x.index, x.title) for x in result] == [
        ("101", 1, "第1章 开始"), ("102", 2, "第2章 继续")]
    assert result[0].url == "https://tomatomtl.com/book/123/101"


def test_invalid_book_url_rejected(tmp_path):
    adapter = TomatoMTLBrowserSource(tmp_path / "browser")
    assert adapter.extract_book_id("https://tomatomtl.com/book/123") == "123"
    for value in ("http://tomatomtl.com/book/123", "https://evil.test/book/123",
                  "https://tomatomtl.com/book/123/456",
                  "https://me@tomatomtl.com/book/123"):
        assert adapter.extract_book_id(value) is None


class _Button:
    def __init__(self, page):
        self.page = page
    @property
    def first(self):
        return self
    def count(self):
        return 1
    def wait_for(self, **kwargs):
        return None
    def click(self, **kwargs):
        self.page.raw = "第30章 时间飞逝\n\n这是通过网页正常按钮复制的完整中文原文，没有更改内容。"


class _Page:
    def __init__(self):
        self.url = "https://tomatomtl.com/book/123/789"
        self.raw = None
    def title(self):
        return "第30章 时间飞逝"
    def locator(self, selector):
        if selector == "body":
            return self
        return _Button(self)
    def inner_text(self, **kwargs):
        return "第30章 时间飞逝 正常阅读内容"
    def evaluate(self, expression):
        if expression == "window.__novelRawCapture = null":
            self.raw = None
        if expression == "window.__novelRawCapture":
            return self.raw
    def wait_for_function(self, expression, **kwargs):
        if not self.raw:
            raise TimeoutError()


def test_raw_click_returns_page_capture_without_os_clipboard(tmp_path, monkeypatch):
    adapter = TomatoMTLBrowserSource(tmp_path / "browser")
    page = _Page()
    monkeypatch.setattr(adapter, "_visit", lambda url: page)
    chapter = ChapterInfo("789", 30, "第30章 时间飞逝",
                          "https://tomatomtl.com/book/123/789")
    content = adapter.get_chapter(chapter)
    assert "第30章 时间飞逝" in content.content
    assert content.remote_id == "789"


def test_raw_capture_failure_does_not_fallback_to_unrelated_text(tmp_path, monkeypatch):
    adapter = TomatoMTLBrowserSource(tmp_path / "browser")
    page = _Page()
    page.locator = lambda selector: _ButtonNeverCopies(page) if selector != "body" else page
    monkeypatch.setattr(adapter, "_visit", lambda url: page)
    chapter = ChapterInfo("789", 30, "第30章 时间飞逝",
                          "https://tomatomtl.com/book/123/789")
    with pytest.raises(RuntimeError, match="Raw click returned no captured text"):
        adapter.get_chapter(chapter)


class _ButtonNeverCopies(_Button):
    def click(self, **kwargs):
        pass


def test_browser_challenge_stops_without_bypass(tmp_path):
    adapter = TomatoMTLBrowserSource(tmp_path / "browser")
    page = _Page()
    page.title = lambda: "Just a moment..."
    with pytest.raises(RuntimeError, match="stopped"):
        adapter._challenge(page)


def test_login_waits_for_user_confirmation_without_deadline(tmp_path, monkeypatch):
    from threading import Event, Thread
    import time
    source = TomatoMTLBrowserSource(tmp_path / "browser")
    page = _Page()
    page.closed = False
    page.is_closed = lambda: page.closed
    page.logged_in = False
    page.locator = lambda selector: _SessionLocator(page) if selector.startswith("a[href") else (
        page if selector == "body" else _Button(page))
    monkeypatch.setattr(source, "_visit", lambda url: page)
    closed = []
    monkeypatch.setattr(source, "close", lambda: closed.append(True))
    confirmed, cancel = Event(), Event()
    ready, waiting, results = [], [], []

    def do_login():
        try:
            results.append(source.prepare_login(
                confirmed, cancel, on_ready=lambda: ready.append(True),
                on_waiting=waiting.append))
        except Exception as exc:
            results.append(exc)

    worker = Thread(target=do_login)
    worker.start()
    try:
        time.sleep(0.4)
        assert ready and worker.is_alive() and not closed
        confirmed.set()
        time.sleep(0.3)
        assert waiting and worker.is_alive()
        page.logged_in = True
        confirmed.set()
        worker.join(3)
        assert results == [True] and closed == [True]
    finally:
        cancel.set()
        worker.join(3)


class _SessionLocator:
    def __init__(self, page):
        self.page = page

    def count(self):
        return int(self.page.logged_in)


def test_login_cancel_closes_context(tmp_path, monkeypatch):
    from threading import Event, Thread
    import time
    adapter = TomatoMTLBrowserSource(tmp_path / "browser")
    page = _Page()
    page.is_closed = lambda: False
    monkeypatch.setattr(adapter, "_visit", lambda url: page)
    closed = []
    monkeypatch.setattr(adapter, "close", lambda: closed.append(True))
    cancel = Event()
    caught = []

    def runner():
        try:
            adapter.prepare_login(Event(), cancel)
        except InterruptedError:
            caught.append(True)

    worker = Thread(target=runner)
    worker.start()
    try:
        time.sleep(0.25)
        assert worker.is_alive()
        cancel.set()
        worker.join(3)
        assert caught == [True] and closed == [True]
    finally:
        cancel.set()
        worker.join(3)
