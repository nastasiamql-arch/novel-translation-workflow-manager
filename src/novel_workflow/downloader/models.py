from dataclasses import asdict, dataclass, field
from uuid import uuid4


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


@dataclass
class DownloaderSourceBinding:
    source_id: str
    book_url: str
    remote_book_id: str
    content_mode: str = "raw_zh"
    last_known_chapter_count: int = 0
    last_downloaded_chapter: int = 0
    last_checked_at: str | None = None
    last_downloaded_at: str | None = None
    skip_existing: bool = True

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            return None
        fields = cls.__dataclass_fields__
        data = {key: item for key, item in value.items() if key in fields}
        if not all(data.get(key) for key in ("source_id", "book_url", "remote_book_id")):
            return None
        return cls(**data)


@dataclass
class DownloaderBook:
    id: str = field(default_factory=lambda: uuid4().hex)
    title: str = "Novel"
    author: str = ""
    source_binding: DownloaderSourceBinding | None = None
    output_dir: str = ""

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Saved Downloader book must be an object")
        data = {key: item for key, item in value.items() if key in cls.__dataclass_fields__}
        data["source_binding"] = DownloaderSourceBinding.from_dict(value.get("source_binding"))
        return cls(**data)

    def to_dict(self):
        return asdict(self)
