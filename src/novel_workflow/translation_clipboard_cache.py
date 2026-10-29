"""Durable, content-verified translation clipboard bundles.

Full source/attachment/output digests are checked on a worker before Ready.
The GUI only performs a cheap stat guard; a changed guard never publishes a
potentially stale bundle. Clipboard-owned entries are pinned across restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .storage import read_json, write_json
from .translation_batches import chapters_for_group, validate_translation_source
from .translation_batch_clipboard import prepare_translation_batch
from .workflow_archive import file_digest, _check_path

CACHE_SCHEMA = 1
MAX_CACHE_BYTES = 2 * 1024 ** 3
MIN_RETENTION_SECONDS = 7 * 24 * 3600


def _stat(path):
    info = Path(path).stat()
    return (info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino)


@dataclass(frozen=True)
class ReadyBundle:
    files: tuple[Path, ...]
    watched: tuple[tuple[Path, tuple], ...]
    directory: tuple[Path, tuple] | None
    cache_entry: Path
    timings: dict

    def is_current(self):
        """Fast guard for normal file changes; full hashes were checked in worker."""
        try:
            if self.directory and _stat(self.directory[0]) != self.directory[1]:
                return False
            return all(path.is_file() and _stat(path) == info for path, info in self.watched)
        except (OSError, ValueError):
            return False


def _watch(source, group, references, files, entry, timings):
    selected = chapters_for_group(source, group)
    inputs = [p for p, _ in source.signatures]
    inputs.extend(references)
    paths = tuple(dict.fromkeys([*inputs, *files]))
    watched = tuple((Path(path), _stat(path)) for path in paths)
    directory = (source.folder, _stat(source.folder)) if source.folder is not None else None
    return ReadyBundle(tuple(files), watched, directory, entry, timings)


def _inside(entry, relative):
    candidate = (entry / relative).resolve(strict=True)
    if not candidate.is_relative_to(entry.resolve()) or not candidate.is_file():
        raise ValueError("ไฟล์ Cache ออกนอกพื้นที่จัดเก็บ")
    return candidate


def prepare_cached_bundle(source, group, references, cache_directory, *,
                          identity, revision, batch_size, as_zip=False, pasted_text=None):
    """Only worker threads may call this function; never access Qt Clipboard."""
    started = time.perf_counter()
    root = Path(cache_directory)
    root.mkdir(parents=True, exist_ok=True)
    references = tuple(_check_path(p) for p in references)
    selected = chapters_for_group(source, group)
    paths = tuple(c.path for c in selected if c.path is not None)
    t = time.perf_counter()
    validate_translation_source(source, text=pasted_text, selected_paths=paths)
    source_ms = (time.perf_counter() - t) * 1000
    t = time.perf_counter()
    reference_hashes = [(str(p), file_digest(p).hex()) for p in references]
    reference_ms = (time.perf_counter() - t) * 1000
    signature_map = {p: digest.hex() for p, digest in source.signatures}
    inputs = [(str(p), signature_map[p]) for p in paths if p in signature_map]
    if source.folder is None:
        inputs = [(str(p), digest.hex()) for p, digest in source.signatures]
    key = {
        "schema": CACHE_SCHEMA, "identity": identity, "revision": revision,
        "group": [group.index, group.start, group.end, [c.number for c in selected]],
        "batch_size": batch_size, "mode": "zip" if as_zip else "files",
        "sources": inputs, "references": reference_hashes,
    }
    tag = hashlib.sha256(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    t = time.perf_counter()
    for entry in sorted(root.glob(tag + "-*"), reverse=True):
        manifest_path = entry / "manifest.json"
        try:
            manifest = read_json(manifest_path, None)
            if (not isinstance(manifest, dict) or json.dumps(manifest.get("key"), sort_keys=True) != json.dumps(key, sort_keys=True)):
                continue
            rels = manifest["files"]
            digests = manifest["digests"]
            if (not isinstance(rels, list) or not rels or len(rels) != len(digests)
                    or any(not isinstance(rel, str) for rel in rels)):
                continue
            files = tuple(_inside(entry, rel) for rel in rels)
            if any(file_digest(p).hex() != digest for p, digest in zip(files, digests)):
                continue
            # Re-check source after expensive archive verification, including
            # changes made by another process during this worker's run.
            validate_translation_source(source, text=pasted_text, selected_paths=paths)
            if [(str(p), file_digest(p).hex()) for p in references] != reference_hashes:
                raise ValueError("ไฟล์ประกอบเปลี่ยนระหว่างตรวจ Cache")
            timings = {
                "source_validation_ms": source_ms, "attachment_hash_ms": reference_ms,
                "cache_lookup_ms": (time.perf_counter() - t) * 1000,
                "cache_preparation_ms": 0.0,
                "worker_total_ms": (time.perf_counter() - started) * 1000,
                "cache_hit": True,
            }
            return _watch(source, group, references, files, entry, timings)
        except (OSError, ValueError, KeyError, TypeError):
            continue
    lookup_ms = (time.perf_counter() - t) * 1000
    entry = Path(tempfile.mkdtemp(prefix=tag + "-", dir=root))
    try:
        t = time.perf_counter()
        files = prepare_translation_batch(
            source, group, references, entry, as_zip=as_zip, pasted_text=pasted_text)
        preparation_ms = (time.perf_counter() - t) * 1000
        manifest = {
            "schema": CACHE_SCHEMA, "key": key,
            "files": [str(p.relative_to(entry)) for p in files],
            "digests": [file_digest(p).hex() for p in files],
            "created_at": time.time(),
        }
        # Input and cached bytes must remain unchanged before Ready.
        validate_translation_source(source, text=pasted_text, selected_paths=paths)
        if [(str(p), file_digest(p).hex()) for p in references] != reference_hashes:
            raise ValueError("ไฟล์ประกอบเปลี่ยนระหว่างเตรียม Cache")
        write_json(entry / "manifest.json", manifest)
        timings = {
            "source_validation_ms": source_ms, "attachment_hash_ms": reference_ms,
            "cache_lookup_ms": lookup_ms, "cache_preparation_ms": preparation_ms,
            "worker_total_ms": (time.perf_counter() - started) * 1000,
            "cache_hit": False,
        }
        return _watch(source, group, references, files, entry, timings)
    except BaseException:
        shutil.rmtree(entry, ignore_errors=True)
        raise


def pin_clipboard_bundle(cache_directory, bundle):
    """Never evict the most recently published clipboard entry, even on restart."""
    root = Path(cache_directory)
    if bundle.cache_entry.parent != root:
        raise ValueError("Cache Clipboard อยู่นอกพื้นที่ที่กำหนด")
    write_json(root / "clipboard-pin.json", {"entry": bundle.cache_entry.name})


def cleanup_translation_cache(cache_directory, *, now=None, max_bytes=MAX_CACHE_BYTES):
    """Conservative LRU cleanup; retain >=7-day clipboard files and pinned entry.

    Run in a background worker only, never during click-to-clipboard.
    In-flight jobs live in the single worker and are never deleted here.
    """
    root = Path(cache_directory)
    if not root.exists():
        return 0
    now = time.time() if now is None else now
    pin = read_json(root / "clipboard-pin.json", {})
    pinned = pin.get("entry") if isinstance(pin, dict) else None
    entries = []
    total = 0
    for entry in root.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        try:
            stat = entry.stat()
            size = sum(p.stat().st_size for p in entry.rglob("*") if p.is_file() and not p.is_symlink())
            entries.append((stat.st_mtime, size, entry))
            total += size
        except OSError:
            continue
    removed = 0
    for modified, size, entry in sorted(entries):
        if entry.name == pinned or now - modified < MIN_RETENTION_SECONDS:
            continue
        # Remove expired orphaned stages and old entries, but never recent
        # files potentially referenced by a clipboard outside this process.
        if total <= max_bytes and now - modified < 30 * 24 * 3600 and (entry / "manifest.json").is_file():
            continue
        shutil.rmtree(entry, ignore_errors=True)
        if not entry.exists():
            total -= size
            removed += 1
    return removed
