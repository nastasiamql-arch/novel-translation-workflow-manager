"""Downloader-owned persistence, separate from Palantir project storage."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from .models import DownloaderBook


def downloader_data_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "NovelDownloader"


def safe_novel_folder_name(title: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", str(title or "").strip())
    name = name.rstrip(" .") or "Untitled Novel"
    if name.upper().split(".", 1)[0] in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        name = "_" + name
    return name[:120].rstrip(" .") or "Untitled Novel"


class DownloaderRepository:
    """Owns the Downloader library, settings, source configs, and manifests."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root) if root is not None else downloader_data_root()
        self.books_path = self.root / "library.json"
        self.settings_path = self.root / "settings.json"
        self.sources_dir = self.root / "sources"
        self.books_dir = self.root / "books"
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.books_dir.mkdir(parents=True, exist_ok=True)

    def list_books(self) -> list[DownloaderBook]:
        value = self._read_json(self.books_path, {"books": []})
        if not isinstance(value, dict) or not isinstance(value.get("books"), list):
            raise ValueError("Downloader library has an unsupported structure")
        return [DownloaderBook.from_dict(item) for item in value["books"]]

    def get_book(self, book_id: str) -> DownloaderBook:
        for book in self.list_books():
            if book.id == book_id:
                return book
        raise ValueError(f"Unknown Downloader book: {book_id}")

    def save_book(self, book: DownloaderBook) -> None:
        books = self.list_books()
        for index, existing in enumerate(books):
            if existing.id == book.id:
                books[index] = book
                break
        else:
            books.append(book)
        self._write_json(self.books_path, {"schema_version": 1, "books": [item.to_dict() for item in books]})

    def remove_book(self, book_id: str) -> None:
        existing = self.list_books()
        books = [book for book in existing if book.id != book_id]
        if len(books) == len(existing):
            raise ValueError(f"Unknown Downloader book: {book_id}")
        self._write_json(self.books_path, {"schema_version": 1, "books": [item.to_dict() for item in books]})

    def load_settings(self) -> dict:
        value = self._read_json(self.settings_path, {})
        if not isinstance(value, dict):
            raise ValueError("Downloader settings have an unsupported structure")
        return value

    def save_settings(self, settings: dict) -> None:
        self._write_json(self.settings_path, settings)

    def manifest_path(self, book_id: str) -> Path:
        if not re.fullmatch(r"[a-fA-F0-9]{32}", book_id):
            raise ValueError("Invalid Downloader book ID")
        return self.books_dir / book_id / "manifest.json"

    def output_path(self, book_id: str, title: str, output_root: str | Path) -> Path:
        self.manifest_path(book_id)  # Validate before constructing paths.
        base = Path(output_root).expanduser().resolve()
        return base / self.novel_folder_name(title, book_id)

    def novel_folder_name(self, title: str, book_id: str) -> str:
        candidate = safe_novel_folder_name(title)
        for book in self.list_books():
            if book.id != book_id and book.output_dir:
                if Path(book.output_dir).name.casefold() == candidate.casefold():
                    return f"{candidate} ({book_id[:6]})"
        return candidate

    @staticmethod
    def _read_json(path: Path, default):
        if not path.is_file():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read Downloader data safely from {path}: {exc}") from exc

    @staticmethod
    def _write_json(path: Path, value) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(value, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
