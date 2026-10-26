"""Collision-safe, preview-first renumbering with backups and explicit restoration."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path, PurePosixPath
import json
import os
import shutil
import tempfile
import uuid
import zipfile

from .chapter_numbering import scan_chapters, format_heading_number
from .novel_file_inspector import Inspection, InspectedFile, decode_text, read_source


@dataclass(frozen=True)
class PlannedFile:
    original: str
    target: str | None
    fingerprint: str
    before: int | None
    after: int | None
    encoding: str


@dataclass
class RenumberPlan:
    source: str
    kind: str
    files: list[PlannedFile]
    start: int
    padding: int
    change_heading: bool


def update_heading(data: bytes, encoding: str, current: int | None, number: int) -> bytes:
    text, detected = decode_text(data)
    if detected != encoding:
        raise ValueError("Encoding changed since inspection")
    headings = scan_chapters(text)
    if current is None or len(headings) != 1 or headings[0].line > 3 or headings[0].number != current:
        raise ValueError("Uncertain chapter heading; use filename-only mode")
    header = headings[0]
    before = text[header.number_start:header.number_end]
    replaced = text[:header.number_start] + format_heading_number(number, before) + text[header.number_end:]
    # Round-trip encoding strictly; preserve UTF-16 byte order/BOM and newlines.
    if encoding == "utf-16" and data.startswith(b"\xfe\xff"):
        return b"\xfe\xff" + replaced.encode("utf-16-be")
    if encoding == "utf-16" and data.startswith(b"\xff\xfe"):
        return b"\xff\xfe" + replaced.encode("utf-16-le")
    return replaced.encode(encoding)


def plan_renumber(result: Inspection, start: int = 1, padding: int = 4,
                  change_heading: bool = False) -> RenumberPlan:
    if result.kind == "combined":
        raise ValueError("TXT รวมบทตรวจได้อย่างเดียว ห้ามจัดเลขไฟล์หรือแก้ต้นฉบับ")
    if not 1 <= start <= 2_147_483_647 or not 1 <= padding <= 12:
        raise ValueError("Invalid chapter start/padding")
    rows = [r for r in result.files if not r.virtual]
    selected = [r for r in rows if r.review != "excluded"]
    if any(r.error or r.review_stale or not r.fingerprint for r in selected):
        raise ValueError("Unreadable or changed files; inspect again")
    if any(r.chapter is None for r in selected):
        raise ValueError("Filename has no unambiguous chapter number")
    chapters = [r.chapter for r in selected]
    if len(chapters) != len(set(chapters)):
        raise ValueError("Ambiguous order: duplicate chapter numbers")
    if start + len(selected) - 1 > 2_147_483_647:
        raise ValueError("Chapter number limit exceeded")
    if change_heading and any(r.heading is None or r.heading != r.chapter for r in selected):
        raise ValueError("Cannot safely edit one or more chapter headings")
    mapping = {r.name: i for i, r in enumerate(sorted(selected, key=lambda r: r.chapter))}
    staged = []
    seen_targets = set()
    for row in rows:
        next_number = start + mapping[row.name] if row.name in mapping else None
        parent = PurePosixPath(row.name).parent
        filename = f"{next_number:0{padding}d}.txt" if next_number is not None else None
        target = str(parent / filename) if filename else None
        if target:
            key = target.casefold()
            if key in seen_targets:
                raise ValueError("Case-insensitive target collision")
            seen_targets.add(key)
        staged.append(PlannedFile(row.name, target, row.fingerprint, row.chapter,
                                  next_number, row.encoding))
    return RenumberPlan(result.source, result.kind, staged, start, padding, change_heading)



def plan_heading_repair(result: Inspection, names: set[str] | None = None,
                        only_changed: bool = False) -> tuple[RenumberPlan, dict[str, str]]:
    """Plan filename-authoritative heading edits, preserving all other files."""
    if result.kind == "combined":
        raise ValueError("TXT รวมบทตรวจได้อย่างเดียว ห้ามแก้ต้นฉบับ")
    selected = set(names) if names is not None else None
    rows = [r for r in result.files if not r.virtual]
    blocked: dict[str, str] = {}
    planned = []
    for row in rows:
        reason = ""
        if selected is not None and row.name not in selected:
            reason = "ไม่ได้เลือก"
        elif row.error or row.review_stale or not row.fingerprint:
            reason = row.error or "ไฟล์เปลี่ยนหรือยังตรวจไม่ได้"
        elif row.chapter is None:
            reason = "ชื่อไฟล์ไม่มีเลขบทที่แน่นอน"
        elif row.heading is None:
            reason = "ไม่พบหัวบทที่แก้ได้อย่างแน่นอน"
        elif row.heading == row.chapter:
            reason = "เลขหัวบทตรงแล้ว"
        if reason:
            blocked[row.name] = reason
        if only_changed and reason:
            continue
        if row.error or row.review_stale or not row.fingerprint:
            continue  # Never copy unreadable/stale files into a claimed validated result.
        planned.append(PlannedFile(row.name, row.name, row.fingerprint,
                                   row.heading if not reason else None,
                                   row.chapter if not reason else None, row.encoding))
    if not planned:
        raise ValueError("ไม่มีไฟล์ TXT ให้แก้")
    return RenumberPlan(result.source, result.kind, planned, 1, 4, True), blocked


def _prepare(plan: RenumberPlan) -> list[tuple[PlannedFile, bytes]]:
    output = []
    for row in plan.files:
        data = read_source(plan.source, plan.kind, row.original)
        if sha256(data).hexdigest() != row.fingerprint:
            raise ValueError(f"Source changed since inspection: {row.original}")
        if row.target is None:
            continue
        if plan.change_heading and row.before is not None and row.after is not None:
            data = update_heading(data, row.encoding, row.before, row.after)
        output.append((row, data))
    return output


def _safe_destination(target: Path, source: Path):
    source = source.resolve()
    if target.exists() or target.is_symlink() or source == target.resolve():
        raise FileExistsError(f"Output already exists or overlaps input: {target}")
    if source.is_dir() and source in target.resolve().parents:
        raise ValueError("Output must not be inside the original source folder")


def _space_check(directory: Path, needed: int):
    if shutil.disk_usage(directory).free < needed + max(16 * 1024 * 1024, needed // 20):
        raise OSError("Insufficient free disk space to preserve source data")


def _write_journal(path: Path, payload: dict):
    fd, name = tempfile.mkstemp(prefix="journal-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def execute_new(plan: RenumberPlan, target: str | Path) -> dict:
    """Create an entirely new output. Source bytes remain untouched."""
    source = Path(plan.source)
    target = Path(target).absolute()
    _safe_destination(target, source)
    payloads = _prepare(plan)
    target.parent.mkdir(parents=True, exist_ok=True)
    _space_check(target.parent, sum(len(data) for _, data in payloads))
    if plan.kind == "zip" or target.suffix.lower() == ".zip":
        if target.suffix.lower() != ".zip":
            raise ValueError("ZIP results require .zip extension")
        fd, name = tempfile.mkstemp(suffix=".zip", dir=target.parent)
        os.close(fd)
        try:
            with zipfile.ZipFile(name, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for row, data in payloads:
                    archive.writestr(row.target, data)
            with zipfile.ZipFile(name) as archive:
                if archive.testzip() is not None:
                    raise IOError("ZIP verification failed")
                for row, data in payloads:
                    if sha256(archive.read(row.target)).digest() != sha256(data).digest():
                        raise IOError("ZIP checksum mismatch")
            if target.exists():
                raise FileExistsError(target)
            os.link(name, target)  # No-clobber publishing of validated ZIP
        finally:
            Path(name).unlink(missing_ok=True)
    else:
        scratch = Path(tempfile.mkdtemp(prefix=".novel-inspector-", dir=target.parent))
        try:
            for row, data in payloads:
                path = scratch / row.target
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            for row, data in payloads:
                if sha256((scratch / row.target).read_bytes()).digest() != sha256(data).digest():
                    raise IOError("Output verification failed")
            if target.exists():
                raise FileExistsError(target)
            os.rename(scratch, target)
        finally:
            if scratch.exists():
                shutil.rmtree(scratch)
    return {"mode": "new", "output": str(target), "changed": sum(r.original != r.target or (plan.change_heading and r.before is not None and r.after is not None and r.before != r.after) for r, _ in payloads),
            "excluded": sum(r.target is None for r in plan.files)}


def execute_in_place(plan: RenumberPlan, backup_root: str | Path) -> dict:
    """Backup first; stage on source filesystem, then publish all renamed files.

    A durable journal and immutable backup are retained if interrupted. On a
    conflicted restore, always produce a separate recovered directory instead.
    """
    if plan.kind != "folder":
        raise ValueError("In-place ZIP changes are not supported")
    source = Path(plan.source).resolve()
    backup_root = Path(backup_root).resolve()
    if source == backup_root or source in backup_root.parents or backup_root in source.parents:
        raise ValueError("Backups must live outside source folder")
    # Prepare and validate all transformations before touching originals.
    payloads = _prepare(plan)
    backup_root.mkdir(parents=True, exist_ok=True)
    _space_check(backup_root, sum((source / file.original).stat().st_size for file in plan.files))
    _space_check(source, sum(len(data) for _, data in payloads))
    source_files = {f.original.casefold() for f in plan.files}
    for row in plan.files:
        if row.target is not None:
            dest = source / row.target
            if dest.is_symlink() or (dest.exists() and row.target.casefold() not in source_files):
                raise FileExistsError(f"Unrelated file blocks target: {row.target}")
    ident = uuid.uuid4().hex
    backup = backup_root / ident
    backup.mkdir(parents=True)
    journal = {"id": ident, "source": str(source), "status": "backing_up",
               "files": [asdict(r) for r in plan.files]}
    _write_journal(backup / "journal.json", journal)
    try:
        for row in plan.files:
            src = source / row.original
            dst = backup / "original" / row.original
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            if sha256(dst.read_bytes()).hexdigest() != row.fingerprint:
                raise IOError("Backup integrity failure")
        journal["status"] = "backup_complete"
        _write_journal(backup / "journal.json", journal)
        # Stage all original files away from their final names to avoid rename cycles.
        stage = source / (".novel_inspector_stage_" + ident)
        stage.mkdir()
        journal["status"] = "applying"
        _write_journal(backup / "journal.json", journal)
        try:
            for row in plan.files:
                src = source / row.original
                dst = stage / row.original
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src, dst)
            for row, data in payloads:
                dst = source / row.target
                dst.parent.mkdir(parents=True, exist_ok=True)
                # Never replace an unrelated file created during transaction.
                with dst.open("xb") as handle:
                    handle.write(data)
            # File exclusion retained exclusively in immutable backup.
            shutil.rmtree(stage)
        except Exception:
            # Avoid overwriting user edits made during an interrupted operation.
            journal["status"] = "recovery_required"
            _write_journal(backup / "journal.json", journal)
            raise
        journal["status"] = "complete"
        journal["result_fingerprints"] = {row.target: sha256(data).hexdigest() for row, data in payloads}
        _write_journal(backup / "journal.json", journal)
        return {"mode": "in_place", "backup": str(backup), "id": ident,
                "changed": sum(row.original != row.target or (plan.change_heading and row.before is not None and row.after is not None and row.before != row.after) for row, _ in payloads),
                "excluded": sum(row.target is None for row in plan.files)}
    except Exception:
        # Incomplete operations never silently claim success; backup persists.
        raise


def restore_backup(backup: str | Path, destination: str | Path) -> str:
    """Never overwrite current user files: restore a separate copy of originals."""
    backup = Path(backup)
    journal = json.loads((backup / "journal.json").read_text(encoding="utf-8"))
    if journal["status"] == "backing_up":
        raise ValueError("Backup was not completed")
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError("Restore output already exists")
    originals = backup / "original"
    for row in journal["files"]:
        p = originals / row["original"]
        if sha256(p.read_bytes()).hexdigest() != row["fingerprint"]:
            raise IOError("Backup content changed")
    shutil.copytree(originals, destination)
    return str(destination)
