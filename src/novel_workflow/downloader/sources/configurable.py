import json
import re
from pathlib import Path
from urllib.parse import urljoin

from selectolax.parser import HTMLParser

from .base import NovelSource
from ..models import BookInfo, ChapterContent, ChapterInfo
from ..http_client import HttpClient


class ConfigurableSource(NovelSource):
    def __init__(self, config, client=None):
        self.config = self.validate(config)
        self.id = self.config["id"]
        self.name = self.config["name"]
        self.domains = tuple(self.config["domains"])
        self.client = client or HttpClient()

    @staticmethod
    def validate(config):
        if not isinstance(config, dict):
            raise ValueError("Source configuration must be a JSON object")
        for key in ("id", "name", "domains", "book", "chapter"):
            if key not in config:
                raise ValueError(f"Source configuration is missing '{key}'")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", str(config["id"])):
            raise ValueError("Source id must use lowercase letters, digits, underscore, or hyphen")
        if not isinstance(config["domains"], list) or not config["domains"]:
            raise ValueError("Source domains must be a non-empty array")
        for section, keys in (("book", ("title", "chapters")), ("chapter", ("title", "content"))):
            if not isinstance(config[section], dict) or any(not isinstance(config[section].get(k), str) or not config[section][k] for k in keys):
                raise ValueError(f"Source '{section}' selectors require: {', '.join(keys)}")
        return config

    def extract_book_id(self, url):
        return re.sub(r"[^a-zA-Z0-9_-]", "", url.rstrip("/").rsplit("/", 1)[-1]) or None

    def get_book(self, url):
        tree = HTMLParser(self.client.get(url).text)
        title = self._text(tree, self.config["book"]["title"])
        if not title:
            raise ValueError("Configured book title selector matched nothing")
        return BookInfo(self.id, self.extract_book_id(url) or "", url, title,
                        self._text(tree, self.config["book"].get("author", "")),
                        language=self.config.get("language", "und"))

    def get_chapters(self, book):
        tree = HTMLParser(self.client.get(book.url).text)
        selector = self.config["book"]["chapters"]
        found = tree.css(selector)
        if not found:
            raise ValueError(f"Configured chapter list selector matched nothing: {selector}")
        return [ChapterInfo(node.attributes.get("href", str(i)), i, node.text().strip(),
                            urljoin(book.url, node.attributes.get("href", "")))
                for i, node in enumerate(found, 1) if node.text().strip()]

    def get_chapter(self, chapter, mode="raw_zh"):
        if mode not in ("raw_zh", "raw"):
            raise ValueError("Configured sources provide raw page text only")
        tree = HTMLParser(self.client.get(chapter.url).text)
        content_selector = self.config["chapter"]["content"]
        node = tree.css_first(content_selector)
        if not node:
            raise ValueError(f"Configured chapter content selector matched nothing: {content_selector}")
        for selector in self.config["chapter"].get("remove", []):
            for unwanted in node.css(selector):
                unwanted.decompose()
        content = node.text(separator="\n").strip()
        if not content:
            raise ValueError("Configured chapter content is empty")
        return ChapterContent(chapter.remote_id, chapter.index, chapter.title, content,
                              self.config.get("language", "und"), chapter.url)

    @staticmethod
    def _text(tree, selector):
        if not selector:
            return ""
        node = tree.css_first(selector)
        return node.text().strip() if node else ""


def load_configurable_sources(directory, *, errors=None):
    root = Path(directory)
    sources = []
    if not root.exists():
        return sources
    for path in sorted(root.glob("*.json")):
        try:
            sources.append(ConfigurableSource(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # Surface individual malformed files so one custom source cannot block others.
            if errors is not None:
                errors.append(f"{path.name}: {exc}")
            continue
    return sources
