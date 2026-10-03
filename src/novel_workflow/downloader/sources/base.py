from abc import ABC, abstractmethod
from urllib.parse import urlparse

from ..models import SourceCapabilities


class NovelSource(ABC):
    id = ""
    name = ""
    domains: tuple[str, ...] = ()
    capabilities = SourceCapabilities()
    min_request_interval = 1.0

    def can_handle(self, url: str) -> bool:
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
            return urlparse(url).scheme in ("http", "https") and any(host == d or host.endswith("." + d) for d in self.domains)
        except ValueError:
            return False

    @abstractmethod
    def extract_book_id(self, url: str) -> str | None: ...
    @abstractmethod
    def get_book(self, url: str): ...
    @abstractmethod
    def get_chapters(self, book): ...
    @abstractmethod
    def get_chapter(self, chapter, mode="raw_zh"): ...
