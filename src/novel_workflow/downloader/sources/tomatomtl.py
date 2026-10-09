import re
from html import unescape
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .base import NovelSource
from ..models import BookInfo, ChapterContent, ChapterInfo, SourceCapabilities
from ..http_client import HttpClient


class TomatoMTLSource(NovelSource):
    id = "tomatomtl"
    name = "TomatoMTL"
    domains = ("tomatomtl.com",)
    min_request_interval = 1.0
    capabilities = SourceCapabilities(supports_raw=True, supports_incremental_update=True)
    _BOOK = re.compile(r"/book/([^/?#]+)")

    def __init__(self, client=None):
        self.client = client or HttpClient(min_interval=self.min_request_interval)

    def extract_book_id(self, url):
        if not self.can_handle(url):
            return None
        match = self._BOOK.search(url)
        return match.group(1) if match else None

    def get_book(self, url):
        book_id = self.extract_book_id(url)
        if not book_id:
            raise ValueError("TomatoMTL book URL must contain /book/<id>")
        response = self.client.get(url)
        text = response.text
        self._check_challenge(text)
        tree = HTMLParser(text)
        title = self._meta(tree, 'meta[property="og:title"]') or self._text(tree, "h1")
        if not title:
            raise ValueError("TomatoMTL did not provide book metadata")
        image = self._meta(tree, 'meta[property="og:image"]')
        author = ""
        chapter_count = 0
        for item in tree.css(".book-meta-item"):
            label = self._text(item, "b").rstrip(":").strip().casefold()
            value = item.text(separator=" ").strip()
            if label == "author":
                author = self._text(item, "#book_author_link a")
            elif label == "chapters":
                match = re.search(r"Chapters:\s*(\d+)", value, re.I)
                if match: chapter_count = int(match.group(1))
        return BookInfo(self.id, book_id, url, title.strip(), author.strip(), image,
                        self._meta(tree, 'meta[name="description"]') or "", "zh", chapter_count)

    def get_chapters(self, book):
        # The /catalog/<book-id> JSON endpoint is called by the site's own catalog-detail.js.
        response = self.client.get(urljoin(book.url, f"/catalog/{book.book_id}"))
        self._check_challenge(response.text)
        try:
            records = response.json()
        except ValueError as exc:
            raise ValueError("TomatoMTL returned an invalid chapter catalog") from exc
        if not isinstance(records, list):
            raise ValueError("TomatoMTL chapter catalog has an unsupported format")
        chapters = []
        for index, item in enumerate(records, 1):
            if not isinstance(item, dict) or not item.get("id") or not item.get("title"):
                raise ValueError(f"TomatoMTL catalog entry {index} is incomplete; no chapters were skipped silently")
            remote_id = str(item["id"])
            if not re.fullmatch(r'[A-Za-z0-9_-]+', remote_id):
                raise ValueError('TomatoMTL catalog contains an unsafe chapter identity')
            chapters.append(ChapterInfo(remote_id, index, unescape(str(item["title"])),
                                        urljoin(book.url, f"/book/{book.book_id}/{remote_id}")))
        if not chapters:
            raise ValueError("TomatoMTL returned an empty chapter catalog")
        return chapters

    def get_chapter(self, chapter, mode="raw_zh"):
        if mode != "raw_zh":
            raise ValueError("TomatoMTL currently supports Chinese Raw / 原文 only")
        if not chapter.url:
            raise ValueError("Chapter URL is missing")
        response = self.client.get(chapter.url)
        self._check_challenge(response.text)
        tree = HTMLParser(response.text)
        node = tree.css_first(".chapter-content")
        content = node.text(separator="\n").strip() if node else ""
        if not content:
            raise ValueError("TomatoMTL chapter content is unavailable")
        han = len(re.findall(r"[\u3400-\u9fff]", content))
        if han < 8 or han / max(1, len(content)) < 0.12:
            raise ValueError("TomatoMTL ไม่ได้ส่งข้อความจีนต้นฉบับที่ตรวจยืนยันได้ จึงไม่บันทึกตอนนี้ กรุณาตรวจการเข้าถึงหน้าตอนบนเว็บไซต์")
        return ChapterContent(chapter.remote_id, chapter.index, chapter.title, content,
                              "zh", chapter.url)

    @staticmethod
    def _check_challenge(text):
        lowered = text.lower()
        if "cdn-cgi/content" in lowered or "just a moment" in lowered or "cf-chl-" in lowered:
            raise RuntimeError("TomatoMTL is presenting an anti-bot challenge. Open the page in your browser; downloader will not bypass it.")

    @staticmethod
    def _meta(tree, selector):
        node = tree.css_first(selector)
        return node.attributes.get("content", "") if node else ""

    @staticmethod
    def _text(tree, selector):
        node = tree.css_first(selector)
        return node.text().strip() if node else ""
