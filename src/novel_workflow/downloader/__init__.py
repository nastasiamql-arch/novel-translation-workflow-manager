"""Website source downloading integrated with novel profiles."""

from .models import BookInfo, ChapterContent, ChapterInfo, DownloadResult, SourceCapabilities
from .registry import SourceRegistry, default_registry
from .service import DownloadService

__all__ = ["BookInfo", "ChapterContent", "ChapterInfo", "DownloadResult", "SourceCapabilities", "SourceRegistry", "default_registry", "DownloadService"]
