import hashlib
import os
import tempfile
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path

from ..models import NovelSourceBinding
from .models import DownloadResult
from .filename import format_chapter_filename
from .manifest import ChapterManifest


class DownloadService:
    def __init__(self, repository, registry):
        self.repository = repository
        self.registry = registry

    def inspect_book(self, url):
        source = self.registry.match(url)
        book = source.get_book(url)
        chapters = source.get_chapters(book)
        if book.total_chapters != len(chapters):
            book = replace(book, total_chapters=len(chapters))
        return source, book

    def bind(self, profile, url, book=None, source=None):
        if source is None or book is None:
            source, book = self.inspect_book(url)
        previous = profile.source_binding
        manifest_path = self.repository.profile_dir(profile.id) / "source_meta" / "manifest.json"
        if previous and (previous.source_id, previous.remote_book_id) != (source.id, book.book_id) and manifest_path.exists():
            archived = manifest_path.with_name(f"manifest.{previous.source_id}.{previous.remote_book_id}.json")
            if not archived.exists():
                archived.parent.mkdir(parents=True, exist_ok=True)
                archived.write_bytes(manifest_path.read_bytes())
            # Start an independent chapter identity map for the newly bound book.
            manifest = ChapterManifest(manifest_path)
            manifest.data = {
                "schema_version": ChapterManifest.SCHEMA_VERSION,
                "source_id": source.id, "book_id": book.book_id,
                "book_url": book.url, "chapters": {},
            }
            manifest.save()
        same_book = bool(previous and (previous.source_id, previous.remote_book_id) == (source.id, book.book_id))
        profile.source_binding = NovelSourceBinding(
            source.id, book.url, book.book_id,
            content_mode=previous.content_mode if same_book else "raw_zh",
            last_known_chapter_count=book.total_chapters,
            last_downloaded_chapter=previous.last_downloaded_chapter if same_book else 0,
            last_checked_at=previous.last_checked_at if same_book else None,
            last_downloaded_at=previous.last_downloaded_at if same_book else None,
            skip_existing=previous.skip_existing if same_book else True,
        )
        self.repository.save_profile(profile)
        manifest = self._manifest(profile)
        manifest.configure(source.id, book.book_id, book.url)
        manifest.save()
        return book

    def check_updates(self, profile):
        binding = self._binding(profile)
        source = self.registry.get(binding.source_id)
        book = source.get_book(binding.book_url)
        if book.book_id != binding.remote_book_id:
            raise ValueError("Source book id changed; confirm the source binding before continuing")
        chapters = source.get_chapters(book)
        manifest = self._manifest(profile)
        known = manifest.data["chapters"]
        missing = [chapter for chapter in chapters
                   if not (known.get(chapter.remote_id, {}).get("downloaded")
                           and (self._source_dir(profile) / known[chapter.remote_id].get("filename", "")).is_file())]
        changed = []
        for chapter in chapters:
            record = known.get(chapter.remote_id)
            if record:
                if record.get("index") not in (None, chapter.index):
                    changed.append(f"{chapter.remote_id}: index {record['index']} → {chapter.index}")
                if record.get("title") not in (None, chapter.title):
                    changed.append(f"{chapter.remote_id}: title {record['title']} → {chapter.title}")
        binding.last_known_chapter_count = len(chapters)
        binding.last_checked_at = datetime.now(timezone.utc).isoformat()
        self.repository.save_profile(profile)
        return {"book": book, "chapters": chapters, "missing": missing,
                "downloaded": len(chapters) - len(missing), "warnings": changed}

    def download_range(self, profile, start, end, skip_existing=True, *, overwrite=False, cancel=None, progress=None):
        if start < 1 or end < start:
            raise ValueError("Chapter range must satisfy 1 ≤ start ≤ end")
        snapshot = self._catalog(profile)
        selected = [item for item in snapshot["chapters"] if start <= item.index <= end]
        return self._download(profile, snapshot, selected, skip_existing, overwrite, cancel, progress)

    def download_missing(self, profile, **kwargs):
        snapshot = self._catalog(profile)
        return self._download(profile, snapshot, snapshot["missing"], **kwargs)

    def download_updates(self, profile, **kwargs):
        return self.download_missing(profile, **kwargs)

    def download_selected(self, profile, chapter_ids, **kwargs):
        snapshot = self._catalog(profile)
        selected = [chapter for chapter in snapshot["chapters"] if chapter.remote_id in set(chapter_ids)]
        return self._download(profile, snapshot, selected, **kwargs)

    def _catalog(self, profile):
        binding = self._binding(profile)
        source = self.registry.get(binding.source_id)
        book = source.get_book(binding.book_url)
        if book.book_id != binding.remote_book_id:
            raise ValueError("Source book id changed; verify the profile binding")
        chapters = source.get_chapters(book)
        manifest = self._manifest(profile)
        known = manifest.data["chapters"]
        missing = [chapter for chapter in chapters
                   if not (known.get(chapter.remote_id, {}).get("downloaded")
                           and (self._source_dir(profile) / known[chapter.remote_id].get("filename", "")).is_file())]
        binding.last_known_chapter_count = len(chapters)
        binding.last_checked_at = datetime.now(timezone.utc).isoformat()
        self.repository.save_profile(profile)
        return {"binding": binding, "source": source, "book": book, "chapters": chapters,
                "missing": missing, "manifest": manifest}

    def _download(self, profile, snapshot, chapters, skip_existing=True, overwrite=False, cancel=None, progress=None):
        result = DownloadResult()
        result.chapters = list(chapters)
        source_dir = self._source_dir(profile)
        source_dir.mkdir(parents=True, exist_ok=True)
        manifest = snapshot.get("manifest") or self._manifest(profile)
        binding = snapshot["binding"]
        client = getattr(snapshot["source"], "client", None)
        if hasattr(client, "cancel_event"):
            client.cancel_event = cancel
        binding.last_known_chapter_count = max(binding.last_known_chapter_count, len(snapshot["chapters"]))
        binding.skip_existing = skip_existing
        total = len(chapters)
        for position, chapter in enumerate(chapters, 1):
            if cancel and cancel.is_set():
                break
            filename = format_chapter_filename(chapter.index, chapter.title)
            target = source_dir / filename
            existing_record = manifest.data["chapters"].get(chapter.remote_id, {})
            if skip_existing and target.is_file() and existing_record.get("downloaded"):
                result.skipped += 1
                if progress: progress(position, total, chapter, result)
                continue
            if target.exists() and not overwrite:
                # Existing untracked files are user data; don't assume they belong to this source.
                result.skipped += 1
                if progress: progress(position, total, chapter, result)
                continue
            try:
                content = snapshot["source"].get_chapter(chapter, mode=binding.content_mode)
                if cancel and cancel.is_set():
                    break
                encoded = content.content.encode("utf-8")
                fd, temporary = tempfile.mkstemp(dir=source_dir, suffix=".tmp")
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(encoded)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target)
                finally:
                    if os.path.exists(temporary): os.unlink(temporary)
                digest = content.content_hash or hashlib.sha256(encoded).hexdigest()
                manifest.record(chapter.remote_id, index=chapter.index, title=chapter.title,
                                filename=filename, content_hash=digest)
                result.downloaded += 1
                binding.last_downloaded_chapter = max(binding.last_downloaded_chapter, chapter.index)
                binding.last_downloaded_at = datetime.now(timezone.utc).isoformat()
                self.repository.save_profile(profile)
            except InterruptedError:
                break
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"{chapter.index} {chapter.title}: {exc}")
            if progress: progress(position, total, chapter, result)
        return result

    def _binding(self, profile):
        if not profile.source_binding:
            raise ValueError("No website source is linked to this profile")
        return profile.source_binding

    def _source_dir(self, profile):
        return self.repository.profile_dir(profile.id) / "source"

    def _manifest(self, profile):
        manifest = ChapterManifest(self.repository.profile_dir(profile.id) / "source_meta" / "manifest.json")
        binding = profile.source_binding
        if binding:
            manifest.configure(binding.source_id, binding.remote_book_id, binding.book_url)
        return manifest
