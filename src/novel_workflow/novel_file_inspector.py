"""Standalone, read-only TXT/ZIP chapter inspection engine.

No translator state, workflow history, or clipboard dependencies. File sizes and
text are bounded before decoding; only fingerprints and metadata are cached.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import re
import statistics
import unicodedata
import zipfile

from .chapter_numbering import scan_chapters

MAX_FILE = 32 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 1024 * 1024 * 1024
MAX_MEMBERS = 100_000
_FILENAME = re.compile(r"^(?P<number>\d+)(?=$|[\s._-])")
_WHITESPACE = re.compile(r"\s+", re.UNICODE)


class UnsafeSource(ValueError):
    """Source cannot be inspected safely."""


@dataclass
class InspectedFile:
    name: str
    chapter: int | None
    size: int
    count: int = 0
    fingerprint: str = ""
    encoding: str = ""
    heading: int | None = None
    reasons: list[str] = field(default_factory=list)
    duplicate_of: str = ""
    review: str = "pending"
    review_stale: bool = False
    error: str = ""
    virtual: bool = False

    @property
    def suspicious(self) -> bool:
        return bool(self.reasons or self.error or self.review_stale or self.virtual)


@dataclass
class Inspection:
    source: str
    kind: str
    files: list[InspectedFile]
    minimum: int = 1500
    cancelled: bool = False

    def summary(self) -> dict[str, int]:
        """Count distinct real files, independently of overlapping issue categories.

        Missing chapters are virtual positions, never damaged files. User review
        decisions are deliberately independent from scanner findings.
        """
        real = [row for row in self.files if not row.virtual]
        flagged = [row for row in real if row.suspicious]
        repairable = [row for row in real if
                      not row.error and not row.review_stale
                      and bool(row.fingerprint) and row.chapter is not None
                      and row.heading is not None and row.chapter != row.heading]
        return {
            "total": len(real),
            "length_pass": sum(not f.error and f.count >= self.minimum for f in real),
            "suspicious": len(flagged),
            "clean": len(real) - len(flagged),
            "missing": sum(f.virtual for f in self.files),
            "heading_mismatch": sum("เลขหัวบทไม่ตรงกับชื่อไฟล์" in f.reasons for f in real),
            "short": sum(not f.error and f.count < self.minimum for f in real),
            "duplicate_content": sum(bool(f.duplicate_of) for f in real),
            "unreadable": sum(bool(f.error) for f in real),
            "repairable": len(repairable),
            "pending_review": sum(f.review == "pending" or f.review_stale for f in flagged),
            "kept": sum(f.review == "keep" and not f.review_stale for f in real),
            "excluded": sum(f.review == "excluded" and not f.review_stale for f in real),
        }

    def shifted_heading_runs(self, minimum_length: int = 3) -> list[list[InspectedFile]]:
        """Find contiguous filenames with the same nonzero heading displacement."""
        ordered = sorted((f for f in self.files if not f.virtual and not f.error
                          and f.chapter is not None and f.heading is not None
                          and f.chapter != f.heading), key=lambda f: (f.chapter, f.name))
        runs: list[list[InspectedFile]] = []
        current: list[InspectedFile] = []
        for row in ordered:
            if (current and (row.chapter != current[-1].chapter + 1
                             or row.heading != current[-1].heading + 1
                             or row.chapter - row.heading != current[-1].chapter - current[-1].heading)):
                if len(current) >= minimum_length:
                    runs.append(current)
                current = []
            current.append(row)
        if len(current) >= minimum_length:
            runs.append(current)
        return runs


def number_from_filename(name: str) -> int | None:
    match = _FILENAME.match(PurePosixPath(name).stem)
    return int(match["number"]) if match and int(match["number"]) > 0 else None


def decode_text(data: bytes) -> tuple[str, str]:
    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode("utf-8-sig"), "utf-8-sig"
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16"
    for encoding in ("utf-8", "gb18030"):
        try:
            text = data.decode(encoding)
            if "\x00" in text or sum(ord(c) < 32 and c not in "\r\n\t" for c in text) > 0:
                raise UnicodeError("binary-like text")
            return text, encoding
        except UnicodeError:
            continue
    raise UnicodeError("ไม่สามารถระบุ Encoding ของข้อความได้อย่างปลอดภัย")


def _without_certain_heading(text: str) -> str:
    headings = scan_chapters(text)
    if len(headings) == 1 and headings[0].line <= 3:
        lines = text.splitlines(keepends=True)
        lines.pop(headings[0].line - 1)
        return "".join(lines)
    return text


def normalize_content(text: str) -> str:
    return _WHITESPACE.sub("", unicodedata.normalize("NFKC", _without_certain_heading(text)))


def count_characters(text: str) -> int:
    return sum(not c.isspace() for c in _without_certain_heading(text))


def valid_zip_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    names = set()
    total = 0
    selected = []
    items = archive.infolist()
    if len(items) > MAX_MEMBERS:
        raise UnsafeSource("ZIP contains too many entries")
    for entry in items:
        path = entry.filename.replace("\\", "/")
        parts = PurePosixPath(path).parts
        pieces = path.rstrip("/").split("/")
        file_type = (entry.external_attr >> 16) & 0o170000
        if (not path or path.startswith("/") or re.match(r"^[a-zA-Z]:", path)
                or any(p in ("", ".", "..") for p in pieces)
                or not parts or entry.flag_bits & 1 or file_type == 0o120000):
            raise UnsafeSource(f"ZIP path/encryption is unsafe: {entry.filename}")
        key = path.casefold()
        if key in names:
            raise UnsafeSource(f"Duplicate ZIP entry: {entry.filename}")
        names.add(key)
        if entry.is_dir():
            continue
        if (entry.file_size > MAX_FILE or
                (entry.file_size and entry.file_size > 200 * max(entry.compress_size, 1))):
            raise UnsafeSource(f"Oversized ZIP entry: {entry.filename}")
        total += entry.file_size
        if total > MAX_ARCHIVE_TOTAL:
            raise UnsafeSource("ZIP expands beyond safety limit")
        if path.lower().endswith(".txt"):
            selected.append(entry)
    return selected


def list_sources(source: str | Path, kind: str) -> list[tuple[str, int]]:
    root = Path(source)
    if kind == "zip":
        with zipfile.ZipFile(root) as z:
            return [(entry.filename, entry.file_size) for entry in valid_zip_members(z)]
    if kind != "folder" or not root.is_dir():
        raise ValueError("Select a directory or ZIP")
    files = []
    for p in root.rglob("*"):
        if p.suffix.lower() == ".txt" and not p.is_symlink() and p.is_file():
            files.append((p.relative_to(root).as_posix(), p.stat().st_size))
    return files


def read_source(source: str | Path, kind: str, name: str) -> bytes:
    if kind == "zip":
        with zipfile.ZipFile(source) as z:
            info = {e.filename: e for e in valid_zip_members(z)}.get(name)
            if info is None:
                raise FileNotFoundError(name)
            with z.open(info) as f:
                data = f.read(MAX_FILE + 1)
    else:
        root = Path(source).resolve()
        lexical = root / name
        if lexical.is_symlink() or any(parent.is_symlink() for parent in lexical.parents if parent != root and root in parent.parents):
            raise UnsafeSource("Symlink source is not supported")
        p = lexical.resolve()
        if root not in p.parents or p.suffix.lower() != ".txt":
            raise UnsafeSource("Path leaves source directory")
        with p.open("rb") as f:
            data = f.read(MAX_FILE + 1)
    if len(data) > MAX_FILE:
        raise UnsafeSource(f"File exceeds {MAX_FILE} byte limit")
    return data


def _bands(normalized: str) -> set[str]:
    """Sparse 4-gram shingles for candidate selection; not a full pairwise matrix."""
    if len(normalized) < 100:
        return set()
    # Stable bottom-k hashed shingles: a short insertion does not shift all
    # sample positions, unlike positional sampling. Bound memory per chapter.
    grams = {sha256(normalized[i:i + 4].encode("utf-8")).digest()[:8]
             for i in range(0, len(normalized) - 3, 2)}
    return set(sorted(grams)[:256])


def inspect(source: str | Path, kind: str = "folder", minimum: int = 1500,
            progress=None, cancelled=None, reviews=None, options=None,
            cache=None) -> Inspection:
    if minimum < 1:
        raise ValueError("Minimum must be positive")
    reviews = reviews or {}
    options = options or {}
    listing = list_sources(source, kind)
    listing.sort(key=lambda it: (number_from_filename(it[0]) is None,
                                 number_from_filename(it[0]) or 0, it[0].casefold()))
    files = []
    exact = {}
    signatures = {}
    buckets = defaultdict(set)
    cache = cache if cache is not None else {}
    archive = zipfile.ZipFile(source) if kind == "zip" else None
    try:
        for index, (name, size) in enumerate(listing):
            if cancelled and cancelled():
                return Inspection(str(source), kind, files, minimum, cancelled=True)
            row = InspectedFile(name, number_from_filename(name), size)
            if size > MAX_FILE:
                row.error = "ไฟล์ใหญ่เกินขีดจำกัดความปลอดภัย"
            else:
                try:
                    if archive is None:
                        stat = (Path(source) / name).stat()
                        stamp = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino]
                    else:
                        info = archive.getinfo(name)
                        stat = Path(source).stat()
                        stamp = [stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                                 info.CRC, info.file_size, info.compress_size]
                    entry = cache.get(name, {})
                    if entry.get("stamp") == stamp and all(k in entry for k in
                            ("fingerprint", "encoding", "heading", "count", "digest", "shingles")):
                        row.fingerprint = entry["fingerprint"]
                        row.encoding = entry["encoding"]
                        row.heading = entry["heading"]
                        row.count = entry["count"]
                        digest = entry["digest"]
                        shingles = set(bytes.fromhex(h) for h in entry["shingles"])
                    else:
                        if archive is not None:
                            with archive.open(name) as stream:
                                data = stream.read(MAX_FILE + 1)
                            if len(data) > MAX_FILE:
                                raise UnsafeSource("ZIP entry expanded beyond safe size")
                        else:
                            data = read_source(source, kind, name)
                        row.fingerprint = sha256(data).hexdigest()
                        text, row.encoding = decode_text(data)
                        headings = scan_chapters(text)
                        row.heading = headings[0].number if len(headings) == 1 and headings[0].line <= 3 else None
                        row.count = count_characters(text)
                        canonical = normalize_content(text)
                        digest = sha256(canonical.encode("utf-8")).hexdigest() if canonical else ""
                        shingles = _bands(canonical)
                        cache[name] = {"stamp": stamp, "fingerprint": row.fingerprint,
                                       "encoding": row.encoding, "heading": row.heading,
                                       "count": row.count, "digest": digest,
                                       "shingles": [h.hex() for h in shingles]}
                    if row.count == 0:
                        row.reasons.append("ไฟล์ว่าง")
                    elif row.count < 500 and options.get("short", True):
                        row.reasons.append("สั้นผิดปกติมาก")
                    elif row.count < minimum and options.get("short", True):
                        row.reasons.append("ต่ำกว่าเกณฑ์")
                    if row.chapter is None:
                        row.reasons.append("อ่านเลขบทจากชื่อไฟล์ไม่ได้")
                    if row.heading is not None and row.chapter is not None and row.heading != row.chapter:
                        row.reasons.append("เลขหัวบทไม่ตรงกับชื่อไฟล์")
                    if digest and options.get("duplicates", True):
                        if digest in exact:
                            row.duplicate_of = exact[digest]
                            row.reasons.append("เนื้อหาซ้ำทั้งหมด")
                        else:
                            exact[digest] = name
                            if len(shingles) >= 25:
                                candidates = Counter(other for key in shingles for other in buckets[key])
                                for previous, overlap in candidates.most_common(32):
                                    old = signatures[previous]
                                    union = len(shingles) + len(old) - overlap
                                    if union and overlap / union >= .92 and abs(len(shingles) - len(old)) <= max(5, len(shingles) // 10):
                                        row.duplicate_of = previous
                                        row.reasons.append("เนื้อหาเกือบเหมือนกัน")
                                        break
                                signatures[name] = shingles
                                for key in shingles:
                                    if len(buckets[key]) < 150:
                                        buckets[key].add(name)
                    review = reviews.get(name)
                    if isinstance(review, dict):
                        row.review = review.get("decision", "pending")
                        row.review_stale = review.get("fingerprint") != row.fingerprint
                        if row.review_stale:
                            row.review = "pending"
                except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, RuntimeError, KeyError) as error:
                    row.error = f"อ่านไฟล์ไม่ได้: {error}"
            files.append(row)
            if progress:
                progress(index + 1, len(listing))
    finally:
        if archive is not None:
            archive.close()
    numbers = Counter(row.chapter for row in files if row.chapter is not None)
    for row in files:
        if row.chapter and numbers[row.chapter] > 1 and options.get("numbers", True):
            row.reasons.append("เลขบทซ้ำ")
    present = sorted(numbers)
    if options.get("missing", True) and present:
        start = max(1, int(options.get("start", present[0])))
        end = int(options.get("end", present[-1]))
        if end >= start and end - start <= 100_000:
            for number in range(start, end + 1):
                if number not in numbers:
                    files.append(InspectedFile(f"(ไม่มีไฟล์บท {number})", number, 0, reasons=["เลขบทขาด"], virtual=True))
    from bisect import bisect_left, bisect_right
    sizes = sorted((r.chapter, r.size) for r in files
                   if r.chapter is not None and not r.virtual and not r.error and r.size > 0)
    chapter_keys = [chapter for chapter, _ in sizes]
    for row in files:
        if row.virtual or row.error or row.chapter is None or not options.get("size", True):
            continue
        lower = bisect_left(chapter_keys, row.chapter - 5)
        upper = bisect_right(chapter_keys, row.chapter + 5)
        neighbors = [size for chapter, size in sizes[lower:upper] if chapter != row.chapter]
        if len(neighbors) >= 3 and row.size < statistics.median(neighbors) * .25:
            row.reasons.append("ขนาดเล็กกว่าบทใกล้เคียงผิดปกติ")
    files.sort(key=lambda row: (row.chapter is None, row.chapter or 0, row.virtual, row.name.casefold()))
    return Inspection(str(source), kind, files, minimum)
