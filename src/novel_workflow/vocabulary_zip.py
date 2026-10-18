"""Lossless, persistent ZIP clipboard files for TXT vocabulary batches.

This is copy-only: it never exports, modifies source files, advances a workflow
step or changes the existing Workflow copy_files_as_zip preference.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from .workflow_archive import _check_path, file_digest, stream_digest


def _members(files: tuple[Path, ...], chapter_count: int) -> tuple[str, ...]:
    """Keep Unicode file names; isolate chapters and step attachments in ZIP."""
    if not 1 <= chapter_count <= len(files):
        raise ValueError("ไม่มีบทต้นฉบับสำหรับสร้าง ZIP")
    names: set[str] = set()
    members = []
    for index, path in enumerate(files):
        section = "chapters" if index < chapter_count else "vocabulary"
        name = path.name
        member = f"{section}/{name}"
        if member.casefold() in names:
            stem, suffix = path.stem, path.suffix
            duplicate = 2
            while f"{section}/{stem} ({duplicate}){suffix}".casefold() in names:
                duplicate += 1
            member = f"{section}/{stem} ({duplicate}){suffix}"
        names.add(member.casefold())
        members.append(member)
    return tuple(members)


def create_txt_batch_zip(paths, chapter_count: int, start: int, end: int,
                         cache_directory: str | Path) -> Path:
    """Atomically publish one validated, distinct and persistent clipboard ZIP.

    Any error occurs before the clipboard is replaced; a failed ZIP is removed
    while a successfully published archive remains available for later paste.
    """
    ordered: list[Path] = []
    seen: set[str] = set()
    for source in paths:
        path = _check_path(source)
        if not path.is_file():
            raise ValueError(f"ไม่ใช่ไฟล์: {path}")
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    if not ordered:
        raise ValueError("ไม่มีไฟล์ที่จะบรรจุใน ZIP")
    if not 1 <= chapter_count <= len(ordered):
        raise ValueError("จำนวนบทสำหรับ ZIP ไม่ถูกต้อง")
    member_names = _members(tuple(ordered), chapter_count)
    signatures = {}
    for path in ordered:
        st = path.stat()
        signatures[path] = ((st.st_size, st.st_mtime_ns, st.st_ino), file_digest(path))
    cache = Path(cache_directory).expanduser()
    cache.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(
        prefix=f"TXT-{start:04d}-{end:04d}-", suffix=".zip", dir=cache,
    )
    os.close(fd)
    archive = Path(filename)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                             allowZip64=True) as zip_out:
            for file, member in zip(ordered, member_names):
                zip_out.write(file, member)
                stat = file.stat()
                if (stat.st_size, stat.st_mtime_ns, stat.st_ino) != signatures[file][0]:
                    raise OSError(f"ไฟล์เปลี่ยนระหว่างสร้าง ZIP: {file}")
        with zipfile.ZipFile(archive, "r") as zip_in:
            if zip_in.testzip() is not None:
                raise OSError("ZIP ไม่ผ่านการตรวจสอบ CRC")
            if len(zip_in.namelist()) != len(ordered):
                raise OSError("จำนวนไฟล์ใน ZIP ไม่ครบ")
            for file, member in zip(ordered, member_names):
                with zip_in.open(member) as stream:
                    archived_digest = stream_digest(stream)
                if archived_digest != signatures[file][1] or file_digest(_check_path(file)) != signatures[file][1]:
                    raise OSError(f"ไฟล์ใน ZIP ไม่ตรงกับต้นฉบับ: {file}")
        return archive
    except BaseException:
        archive.unlink(missing_ok=True)
        raise
