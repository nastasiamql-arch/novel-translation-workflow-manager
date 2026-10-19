"""Validated copy-only translation bundles with persistent clipboard cache."""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from .clipboard_files import copy_file_paths
from .translation_batches import chapters_for_group, validate_translation_source
from .workflow_archive import _check_path, file_digest, stream_digest


def prepare_translation_batch(source, group, references, cache_directory, *,
                              as_zip=False, pasted_text=None):
    """Publish only after all inputs verify; never mutate the original source."""
    validate_translation_source(source, text=pasted_text)
    selected = chapters_for_group(source, group)
    references = tuple(_check_path(p) for p in references)
    root = Path(cache_directory)
    root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="Translation-", dir=root))
    entries = []
    input_hashes = {p: file_digest(p) for p in references}
    try:
        for chapter in selected:
            if chapter.path is not None:
                src = _check_path(chapter.path)
                input_hashes.setdefault(src, file_digest(src))
                payload = src.read_bytes()
            else:
                payload = chapter.content
            if payload is None:
                raise ValueError(f"บท {chapter.number} ไม่มีเนื้อหา")
            destination = stage / "source" / chapter.filename
            if destination.exists():
                raise ValueError(f"ชื่อไฟล์บทซ้ำ: {chapter.filename}")
            destination.parent.mkdir(exist_ok=True)
            destination.write_bytes(payload)
            if destination.read_bytes() != payload:
                raise OSError(f"ไฟล์บทไม่ตรงต้นฉบับ: {chapter.filename}")
            entries.append((destination, f"source/{chapter.filename}"))
        occupied = {name.casefold() for _, name in entries}
        for i, path in enumerate(references, 1):
            name = f"references/{path.name}"
            if name.casefold() in occupied:
                raise ValueError(f"ชื่อไฟล์ประกอบซ้ำ: {path.name}")
            occupied.add(name.casefold())
            destination = stage / "references" / path.name
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(path, destination)
            if file_digest(destination) != input_hashes[path]:
                raise OSError(f"ไฟล์ประกอบเปลี่ยนระหว่างคัดลอก: {path.name}")
            entries.append((destination, name))
        validate_translation_source(source, text=pasted_text)
        for path, digest in input_hashes.items():
            if file_digest(_check_path(path)) != digest:
                raise OSError(f"ไฟล์เปลี่ยนระหว่างเตรียมคัดลอก: {path.name}")
        if not as_zip:
            return tuple(file for file, _ in entries)
        fd, name = tempfile.mkstemp(prefix=f"Translation-{group.start:04d}-{group.end:04d}-",
                                    suffix=".zip", dir=root)
        os.close(fd)
        archive = Path(name)
        try:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as out:
                for file, member in entries:
                    out.write(file, member)
            with zipfile.ZipFile(archive) as check:
                if check.testzip() is not None or set(check.namelist()) != {n for _, n in entries}:
                    raise OSError("ZIP ไม่ผ่านการตรวจสอบ")
                for file, member in entries:
                    with check.open(member) as stream:
                        if stream_digest(stream) != file_digest(file):
                            raise OSError(f"ZIP มีเนื้อหาไม่ตรงกัน: {member}")
            return (archive,)
        except BaseException:
            archive.unlink(missing_ok=True)
            raise
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def copy_translation_batch(source, group, references, cache_directory, *,
                           as_zip=False, pasted_text=None):
    """Qt clipboard is changed only after a complete verified bundle exists."""
    files = prepare_translation_batch(
        source, group, references, cache_directory,
        as_zip=as_zip, pasted_text=pasted_text
    )
    return copy_file_paths(files)
