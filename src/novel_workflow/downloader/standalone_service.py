"""Sequential Raw chapter jobs, completely independent of translation profiles."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path

from .models import DownloadResult
from .standalone_storage import DownloaderRepository, _atomic_bytes, _read_json
from .filename import format_chapter_filename


class RateBudget:
    """Persist request starts across jobs; limits apply to all Downloader books."""

    def __init__(self, store: DownloaderRepository, *, delay=10, hourly=90, daily=500,
                 clock=time.time):
        self.store, self.clock = store, clock
        self.delay = max(10, int(delay))
        self.hourly, self.daily = int(hourly), int(daily)
        if not (1 <= self.hourly <= 121 and 1 <= self.daily <= 676):
            raise ValueError("Invalid chapter-request budget")

    def wait(self, cancel=None):
        while True:
            now = self.clock()
            history = _read_json(self.store.limits_path, {"attempts": []}).get("attempts", [])
            if not isinstance(history, list) or any(not isinstance(x, (int, float)) for x in history):
                raise ValueError("Invalid request history")
            history = [x for x in history if 0 <= now - x < 86400]
            hour = [x for x in history if now - x < 3600]
            delays = [0.0]
            if history:
                delays.append(history[-1] + self.delay - now)
            if len(hour) >= self.hourly:
                delays.append(hour[-self.hourly] + 3600 - now)
            if len(history) >= self.daily:
                delays.append(history[-self.daily] + 86400 - now)
            sleep = max(delays)
            if sleep <= 0:
                history.append(now)
                _atomic_bytes(self.store.limits_path,
                              __import__("json").dumps({"attempts": history}).encode("utf-8"))
                return
            if cancel and cancel.wait(min(sleep, 1)):
                raise InterruptedError("Download paused")
            if not cancel:
                time.sleep(min(sleep, 1))
            elif cancel.is_set():
                raise InterruptedError("Download paused")


def cleaned_raw(text: str, chapter) -> str:
    """Keep Chinese paragraphs intact; strip only the verified footer signature."""
    raw = str(text).replace("\r\n", "\n").replace("\r", "\n").strip()
    raw = re.sub(
        r"\n\s*TomatoMTL\s*[–-]\s*Advanced MTL Reading Assist Tool\s*\n"
        r"URL:\s*https://tomatomtl\.com/book/[0-9]+/[A-Za-z0-9_-]+/?\s*$",
        "", raw, flags=re.I,
    ).strip()
    error_phrases = ("error: failed to fetch", "just a moment", "access denied",
                     "captcha", "failed to load catalog")
    if not raw or any(message in raw.lower() for message in error_phrases):
        raise ValueError("Raw text unavailable or contains an access/error page")
    count = len(re.findall(r"[\u3400-\u9fff]", raw))
    if count < 8 or count / max(1, len(raw)) < 0.12:
        raise ValueError("Raw chapter is not verifiable Chinese text")
    heading = raw.splitlines()[0].strip()
    if not re.match(r"^第.{1,14}[章节回卷]", heading):
        raise ValueError("Raw chapter heading is missing; refusing to invent source text")
    numbered = re.match(r"^第([0-9]{1,8})[章节回]", heading)
    if numbered and int(numbered.group(1)) != chapter.index:
        raise ValueError(f"Raw chapter number {numbered.group(1)} differs from catalog {chapter.index}")
    return raw + "\n"


class StandaloneDownloadService:
    def __init__(self, store: DownloaderRepository, registry):
        self.store, self.registry = store, registry

    def inspect(self, url: str):
        source = self.registry.match(url)
        try:
            book = source.get_book(url)
            chapters = source.get_chapters(book)
            return book, chapters
        finally:
            closer = getattr(source, "close", None)
            if callable(closer):
                closer()

    def download_range(self, book_id: str, start: int, end: int, *,
                       mode="both", digits=4, include_title=False,
                       delay=10, hourly=90, daily=500,
                       cancel=None, progress=None):
        entry = self.store.get_book(book_id)
        source = self.registry.get(entry["source_id"])
        try:
            return self._download_range(book_id, start, end, mode=mode, digits=digits,
                                        include_title=include_title, delay=delay,
                                        hourly=hourly, daily=daily, cancel=cancel,
                                        progress=progress)
        finally:
            closer = getattr(source, "close", None)
            if callable(closer):
                closer()

    def _download_range(self, book_id: str, start: int, end: int, *,
                        mode="both", digits=4, include_title=False,
                        delay=10, hourly=90, daily=500,
                        cancel=None, progress=None):
        if start < 1 or end < start or mode not in {"separate", "combined", "both"}:
            raise ValueError("Invalid chapter range or output mode")
        if not 1 <= int(digits) <= 8:
            raise ValueError("Filename digits must be between 1 and 8")
        entry = self.store.get_book(book_id)
        source = self.registry.get(entry["source_id"])
        book = source.get_book(entry["url"])
        if book.book_id != entry["book_id"]:
            raise ValueError("Source book changed; do not mix chapter files")
        chapters = source.get_chapters(book)
        selected = [item for item in chapters if start <= item.index <= end]
        if not selected:
            raise ValueError("No chapters in selected range")
        output = Path(entry["output_dir"]).expanduser().resolve()
        profiles = self.store.root.parent / "profiles"
        if output == profiles or profiles in output.parents:
            raise ValueError("Destination overlaps translation profiles")
        manifest = self.store.manifest(book_id)
        manifest.configure(entry["source_id"], entry["book_id"], entry["url"])
        budget = RateBudget(self.store, delay=delay, hourly=hourly, daily=daily)
        result = DownloadResult(chapters=list(selected))
        client = getattr(source, "client", None)
        if hasattr(client, "cancel_event"):
            client.cancel_event = cancel
        ready = []
        for position, chapter in enumerate(selected, 1):
            if cancel and cancel.is_set():
                break
            try:
                cache = self.store.cache_path(book_id, chapter.remote_id)
                record = manifest.data["chapters"].get(chapter.remote_id, {})
                content = cache.read_bytes() if cache.is_file() else b""
                valid = bool(content and record.get("content_hash") ==
                             hashlib.sha256(content).hexdigest())
                if not valid:
                    budget.wait(cancel)
                    fetched = source.get_chapter(chapter, mode="raw_zh")
                    if cancel and cancel.is_set():
                        break
                    content = cleaned_raw(fetched.content, chapter).encode("utf-8")
                    _atomic_bytes(cache, content)
                    manifest.record(chapter.remote_id, index=chapter.index, title=chapter.title,
                                    filename=cache.name, content_hash=hashlib.sha256(content).hexdigest())
                    result.downloaded += 1
                else:
                    result.skipped += 1
                ready.append((chapter, content))
                if mode in ("separate", "both"):
                    if include_title:
                        source_prefix = f"{chapter.index:04d} "
                        safe_title = format_chapter_filename(chapter.index, chapter.title)
                        filename = f"{chapter.index:0{int(digits)}d} " + safe_title[len(source_prefix):]
                    else:
                        filename = f"{chapter.index:0{int(digits)}d}.txt"
                    target = output / "Chapters" / filename
                    if not target.exists():
                        _atomic_bytes(target, content)
                    elif target.read_bytes() != content:
                        raise FileExistsError(f"Existing TXT differs; never overwrite automatically: {target.name}")
            except InterruptedError:
                break
            except Exception as exc:
                result.failed += 1
                result.errors.append(f"บท {chapter.index}: {exc}")
                if any(term in str(exc).lower() for term in
                       ("429", "captcha", "challenge", "access denied", "rate limit", "failed to fetch")):
                    result.errors.append("Stopped: website access is blocked or limited")
                    if progress: progress(position, len(selected), chapter, result)
                    break
            if progress:
                progress(position, len(selected), chapter, result)
        if mode in ("combined", "both") and len(ready) == len(selected) and result.failed == 0:
            assembled = b"\n".join(text for _, text in ready)
            target = output / "Novel_All.txt"
            if target.exists() and target.read_bytes() != assembled:
                result.errors.append("Existing Novel_All.txt differs; not overwritten")
                result.failed += 1
            elif not target.exists():
                _atomic_bytes(target, assembled)
        return result
