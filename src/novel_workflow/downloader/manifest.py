import json
import os
import tempfile
from pathlib import Path
from datetime import datetime, timezone


class ManifestError(ValueError):
    pass


class ChapterManifest:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = self.load()

    def load(self):
        if not self.path.exists():
            return {"schema_version": self.SCHEMA_VERSION, "source_id": "", "book_id": "", "book_url": "", "chapters": {}}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"Cannot read chapter manifest safely: {exc}") from exc
        if not isinstance(value, dict) or not isinstance(value.get("chapters"), dict):
            raise ManifestError("Chapter manifest has an unsupported structure")
        if value.get("schema_version", 1) != self.SCHEMA_VERSION:
            raise ManifestError(f"Unsupported chapter manifest version: {value.get('schema_version')}")
        value.setdefault("schema_version", self.SCHEMA_VERSION)
        return value

    def configure(self, source_id, book_id, book_url):
        self.data.update(source_id=source_id, book_id=book_id, book_url=book_url)

    def is_downloaded(self, remote_id, source_dir):
        record = self.data["chapters"].get(str(remote_id), {})
        return bool(record.get("downloaded") and (Path(source_dir) / record.get("filename", "")).is_file())

    def record(self, remote_id, *, index, title, filename, content_hash):
        self.data["chapters"][str(remote_id)] = {
            "index": index, "title": title, "filename": filename,
            "downloaded": True, "content_hash": content_hash,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            fd, name = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(self.data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
