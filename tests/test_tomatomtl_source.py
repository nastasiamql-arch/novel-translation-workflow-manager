import json
from pathlib import Path

import pytest

from novel_workflow.downloader.models import BookInfo, ChapterInfo
from novel_workflow.downloader.sources.tomatomtl import TomatoMTLSource


class Response:
    def __init__(self, text, data=None): self.text, self.data = text, data
    def json(self): return self.data if self.data is not None else json.loads(self.text)


class Client:
    def __init__(self, responses): self.responses = iter(responses)
    def get(self, url): return next(self.responses)


def test_catalog_parser_uses_catalog_shape_and_raw_chinese_page():
    fixture = (Path(__file__).parent / "fixtures" / "tomatomtl_catalog.json").read_text(encoding="utf-8")
    source = TomatoMTLSource(Client([Response(fixture),
                                    Response('<div class="chapter-content"><p>这是中文原文内容，确保它不是机器翻译的英文文本。</p></div>')]))
    book = BookInfo("tomatomtl", "123", "https://tomatomtl.com/book/123", "小说")
    chapter = source.get_chapters(book)[0]
    assert chapter.index == 1 and chapter.remote_id == "7505707639456678425"
    assert source.get_chapter(chapter).content.startswith("这是中文")


def test_book_metadata_reads_title_author_and_chapter_count():
    fixture = (Path(__file__).parent / "fixtures" / "tomatomtl_book.html").read_text(encoding="utf-8")
    source = TomatoMTLSource(Client([Response(fixture)]))
    book = source.get_book("https://tomatomtl.com/book/7505707616878742553")
    assert book.title == "F1 Journey: The Road To Championship"
    assert book.author == "Sample author"
    assert book.total_chapters == 381


def test_challenge_and_non_raw_content_are_rejected():
    source = TomatoMTLSource(Client([Response('<html>Just a moment <div class="cf-chl">')]))
    with pytest.raises(RuntimeError, match="will not bypass"):
        source.get_chapter(ChapterInfo("1", 1, "第一章", "https://tomatomtl.com/book/1/1"))
    source = TomatoMTLSource(Client([Response('<div class="chapter-content">English translated words only</div>')]))
    with pytest.raises(ValueError, match="verifiable Chinese raw text"):
        source.get_chapter(ChapterInfo("1", 1, "第一章", "https://tomatomtl.com/book/1/1"))
