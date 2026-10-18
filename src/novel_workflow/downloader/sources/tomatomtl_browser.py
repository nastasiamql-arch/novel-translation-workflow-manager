"""Visible Chrome/Edge TomatoMTL reader. No access-control bypass."""
from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

from .base import NovelSource
from ..models import BookInfo, ChapterContent, ChapterInfo, SourceCapabilities

# Capture only a page-initiated Raw copy in the isolated browser context.
# No Windows Clipboard reads/writes or reuse of the user's Chrome profile.
_COPY_CAPTURE = """
(() => {
  window.__novelRawCapture = null;
  const capture = async text => {
    window.__novelRawCapture = String(text);
  };
  try {
    if (navigator.clipboard) {
      Object.defineProperty(navigator.clipboard, 'writeText', {
        configurable: true, value: capture
      });
    }
  } catch (_) { /* Site may restrict Clipboard API; fail closed below. */ }
})();
"""

_BOOK_URL = re.compile(r"^/book/([0-9]+)/?$")
_CHAPTER_LABEL = re.compile(r"^(?:第.{1,16}[章节回卷]|番外|序章|楔子)")


def chapter_links(book: BookInfo, links: list[dict]) -> list[ChapterInfo]:
    """Only catalog-like chapter links after chapter one; no Latest/Continue."""
    prefix = f"/book/{book.book_id}/"
    candidates = []
    seen = set()
    for link in links:
        target = urlparse(str(link.get("href") or ""))
        if target.scheme != "https" or target.hostname != "tomatomtl.com":
            continue
        path = target.path.rstrip("/")
        if not path.startswith(prefix):
            continue
        remote_id = path[len(prefix):]
        if not re.fullmatch(r"[0-9]+", remote_id) or remote_id in seen:
            continue
        title = unescape(str(link.get("title") or "").strip())
        if not _CHAPTER_LABEL.match(title):
            continue
        seen.add(remote_id)
        candidates.append((remote_id, title, "https://tomatomtl.com" + path))
    # Book pages can show Latest before the chapter list. Start at chapter 1.
    first = next((i for i, (_, title, _) in enumerate(candidates)
                  if re.match(r"^第[一1壹][章节回]", title)), None)
    if first is None:
        raise ValueError("TomatoMTL book page did not display chapter 1")
    chapters = [ChapterInfo(remote, i, title, url)
                for i, (remote, title, url) in enumerate(candidates[first:], 1)]
    if not chapters:
        raise ValueError("TomatoMTL catalog is empty")
    return chapters


class TomatoMTLBrowserSource(NovelSource):
    id = "tomatomtl"
    name = "TomatoMTL · Chrome/Edge"
    domains = ("tomatomtl.com",)
    capabilities = SourceCapabilities(supports_raw=True, supports_incremental_update=True)

    def __init__(self, browser_profile: Path):
        self.browser_profile = Path(browser_profile)
        self._playwright = None
        self._context = None
        self._page = None

    def extract_book_id(self, url: str) -> str | None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "tomatomtl.com" or parsed.username:
            return None
        match = _BOOK_URL.fullmatch(parsed.path)
        return match.group(1) if match else None

    def _launch(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright is not installed with Novel Downloader") from exc
        self.browser_profile.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        channels = []
        try:
            for channel in ("chrome", "msedge"):
                try:
                    self._context = self._playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.browser_profile), channel=channel, headless=False,
                        accept_downloads=False, viewport={"width": 1280, "height": 850},
                    )
                    break
                except Exception as exc:
                    channels.append(f"{channel}: {type(exc).__name__}")
            if not self._context:
                raise RuntimeError("Unable to open Chrome or Edge. Install one of them first. "
                                   + ", ".join(channels))
            self._context.add_init_script(_COPY_CAPTURE)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            self._page.set_default_timeout(20000)
            return self._page
        except Exception:
            self.close()
            raise

    @staticmethod
    def _challenge(page):
        title = page.title().lower()
        if any(word in title for word in ("just a moment", "access denied", "captcha")):
            raise RuntimeError("Website access verification detected; downloader stopped")
        body = page.locator("body").inner_text(timeout=15000)[:1000].lower()
        if any(word in body for word in ("checking your browser", "verify you are human")):
            raise RuntimeError("Website access verification detected; downloader stopped")

    def _visit(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "tomatomtl.com" or parsed.username:
            raise ValueError("Only HTTPS TomatoMTL URLs are supported")
        page = self._launch()
        response = page.goto(url, wait_until="domcontentloaded", timeout=45000)
        if response and response.status in (401, 403, 429):
            raise RuntimeError(f"Website refused browser access (HTTP {response.status}); stopped")
        if urlparse(page.url).hostname != "tomatomtl.com":
            raise RuntimeError("Unexpected redirect away from TomatoMTL")
        self._challenge(page)
        return page

    def get_book(self, url: str):
        book_id = self.extract_book_id(url)
        if book_id is None:
            raise ValueError("Enter a valid TomatoMTL book URL /book/<id>")
        page = self._visit(url)
        title = page.locator("h1").first.inner_text().strip() if page.locator("h1").count() else ""
        if not title:
            meta = page.locator("meta[property='og:title']")
            title = (meta.first.get_attribute("content") or "").strip() if meta.count() else ""
        if not title:
            raise ValueError("TomatoMTL title was not visible in browser")
        return BookInfo(self.id, book_id, url, title)

    def get_chapters(self, book):
        page = self._visit(book.url)
        # Observe the rendered catalog, not a direct HTTP catalog endpoint.
        page.wait_for_function(
            """bookId => [...document.querySelectorAll('a[href]')].some(a =>
                a.href.includes('/book/' + bookId + '/') &&
                /^第[一1壹][章节回]/.test(a.textContent.trim()))""",
            arg=book.book_id, timeout=30000,
        )
        links = page.locator("a[href]").evaluate_all(
            """items => items.map(a => ({href: a.href, title: a.textContent}))"""
        )
        return chapter_links(book, links)

    def get_chapter(self, chapter, mode="raw_zh"):
        if mode != "raw_zh" or not chapter.url:
            raise ValueError("Chinese Raw requires a valid chapter URL")
        page = self._visit(chapter.url)
        # The actual page uses <button title="Copy Raw Text">Raw</button>.
        button = page.locator('button[title="Copy Raw Text"]')
        if not button.count():
            button = page.get_by_role("button", name=re.compile(r"^Raw$", re.I))
        button.first.wait_for(state="visible", timeout=20000)
        page.evaluate("window.__novelRawCapture = null")
        button.first.click(timeout=15000)
        try:
            page.wait_for_function(
                "() => typeof window.__novelRawCapture === 'string' && "
                "window.__novelRawCapture.length > 0", timeout=12000)
        except Exception as exc:
            self._challenge(page)
            raise RuntimeError("Raw click returned no captured text; stopping rather than "
                               "using unrelated clipboard or translated text") from exc
        text = page.evaluate("window.__novelRawCapture")
        if not text:
            raise ValueError("Raw text was empty")
        return ChapterContent(chapter.remote_id, chapter.index, chapter.title,
                              text, "zh", chapter.url)

    def close(self):
        context, driver = self._context, self._playwright
        self._page = self._context = self._playwright = None
        if context:
            try:
                context.close()
            except Exception:
                pass
        if driver:
            try:
                driver.stop()
            except Exception:
                pass
