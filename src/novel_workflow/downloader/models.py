from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceCapabilities:
    supports_raw: bool = True
    supports_translation: bool = False
    supports_incremental_update: bool = True
    supports_login: bool = False
    supports_images: bool = False


@dataclass(frozen=True)
class BookInfo:
    source_id: str
    book_id: str
    url: str
    title: str
    author: str = ""
    cover_url: str | None = None
    description: str = ""
    language: str = "zh"
    total_chapters: int = 0
    extra: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ChapterInfo:
    remote_id: str
    index: int
    title: str
    url: str | None = None
    published_at: str | None = None


@dataclass(frozen=True)
class ChapterContent:
    remote_id: str
    index: int
    title: str
    content: str
    language: str = "zh"
    source_url: str = ""
    content_hash: str | None = None


@dataclass
class DownloadResult:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    chapters: list[ChapterInfo] = field(default_factory=list)
