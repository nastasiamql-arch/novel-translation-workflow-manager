from __future__ import annotations

import shutil
from pathlib import Path


SUPPORTED_IMPORT_SUFFIXES = {".txt", ".md", ".json"}


def import_files_into_directory(sources, destination: Path) -> tuple[int, int]:
    """Copy supported files into a project directory, skipping name conflicts.

    Returns the number copied and skipped. The caller is responsible for
    resolving and validating the destination inside the project root.
    """
    destination.mkdir(parents=True, exist_ok=True)
    copied = skipped = 0
    for source in sources:
        source = Path(source)
        if source.suffix.lower() not in SUPPORTED_IMPORT_SUFFIXES or not source.is_file():
            skipped += 1
            continue
        target = destination / source.name
        if target.exists():
            skipped += 1
            continue
        shutil.copy2(source, target)
        copied += 1
    return copied, skipped
