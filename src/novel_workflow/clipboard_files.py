"""Single Windows Explorer-compatible clipboard path for workflow and TXT batches."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QApplication


def copy_file_paths(paths) -> tuple[Path, ...]:
    """Copy real local files to CF_HDROP/URI clipboard without changing file bytes.

    Validate every path before touching the clipboard, deduplicate by resolved
    path (case-insensitively on Windows), and never create a ZIP or text bundle.
    """
    ordered = []
    seen = set()
    for source in paths:
        path = Path(source).expanduser().resolve(strict=True)
        if not path.is_file():
            raise ValueError(f"ไม่ใช่ไฟล์: {path}")
        key = str(path).casefold()
        if key not in seen:
            seen.add(key)
            ordered.append(path)
    if not ordered:
        raise ValueError("ไม่มีไฟล์ให้คัดลอก")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path)) for path in ordered])
    QApplication.clipboard().setMimeData(mime)
    return tuple(ordered)
