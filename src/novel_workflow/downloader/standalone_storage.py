"""Storage exclusive to Novel Downloader; never accesses Novel Profiles."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .manifest import ChapterManifest


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _read_json(path: Path, fallback: dict) -> dict:
    if not path.is_file():
        return fallback
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Invalid Downloader storage: {path}")
    return data


class DownloaderRepository:
    """Independent book library and manifest storage under NovelWorkflow/downloader."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.library_path = self.root / "library.json"
        self.limits_path = self.root / "request_history.json"

    def list_books(self) -> list[dict]:
        data = _read_json(self.library_path, {"schema_version": 1, "books": []})
        if data.get("schema_version") != 1 or not isinstance(data.get("books"), list):
            raise ValueError("Unsupported Downloader library schema")
        return data["books"]

    @staticmethod
    def identity(source_id: str, book_id: str) -> str:
        return hashlib.sha256(f"{source_id}:{book_id}".encode("utf-8")).hexdigest()[:24]

    def save_book(self, book, output_dir: Path, *, mode="both", digits=4, include_title=False) -> dict:
        if not output_dir or not str(output_dir).strip():
            raise ValueError("Select a destination folder")
        output = Path(output_dir).expanduser().resolve()
        profiles = self.root.parent / "profiles"
        if output == profiles or profiles in output.parents:
            raise ValueError("Downloader cannot write into translation profile storage")
        key = self.identity(book.source_id, book.book_id)
        entry = {"id": key, "source_id": book.source_id, "book_id": book.book_id,
                 "url": book.url, "title": book.title, "output_dir": str(output),
                 "mode": mode, "digits": int(digits), "include_title": bool(include_title)}
        books = [item for item in self.list_books() if item.get("id") != key]
        books.append(entry)
        _atomic_bytes(self.library_path, json.dumps(
            {"schema_version": 1, "books": books}, ensure_ascii=False, indent=2
        ).encode("utf-8"))
        return entry

    def get_book(self, book_id: str) -> dict:
        return next((item for item in self.list_books() if item.get("id") == book_id),
                    None) or self._missing(book_id)

    @staticmethod
    def _missing(book_id):
        raise ValueError(f"Unknown Downloader book: {book_id}")

    def book_root(self, book_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{24}", book_id):
            raise ValueError("Invalid Downloader book identity")
        return self.root / "books" / book_id

    def manifest(self, book_id: str) -> ChapterManifest:
        return ChapterManifest(self.book_root(book_id) / "manifest.json")

    def cache_path(self, book_id: str, remote_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", str(remote_id)):
            raise ValueError("Unsafe remote chapter identity")
        return self.book_root(book_id) / "cache" / (str(remote_id) + ".txt")
