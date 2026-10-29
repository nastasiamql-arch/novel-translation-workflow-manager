"""Persistent cache and prioritized translation prewarming regressions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from time import perf_counter

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from novel_workflow.batch_copy_history import index_group_copy_status
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batches import load_translation_source, translation_groups
from novel_workflow.translation_clipboard_cache import (
    prepare_cached_bundle, pin_clipboard_bundle, cleanup_translation_cache,
)
from novel_workflow.translation_batch_page import TranslationBatchPage


def _source(tmp_path, count=8):
    folder = tmp_path / "source"
    folder.mkdir()
    for i in range(1, count + 1):
        (folder / f"{i:04}.txt").write_bytes(f"第{i}章\n正文 {i}\n".encode())
    return folder, load_translation_source("folder", path=folder)


def test_cache_hit_reuses_exact_bytes_and_invalidates_modified_source(tmp_path):
    folder, source = _source(tmp_path)
    group = translation_groups(source, 4)[0]
    attachment = tmp_path / "Context.md"
    attachment.write_bytes(b"Context 1")
    kwargs = dict(identity="profile/source", revision="revision1", batch_size=4)
    cold = prepare_cached_bundle(source, group, (attachment,), tmp_path / "cache", **kwargs)
    warm = prepare_cached_bundle(source, group, (attachment,), tmp_path / "cache", **kwargs)
    assert not cold.timings["cache_hit"]
    assert warm.timings["cache_hit"]
    assert cold.files == warm.files
    assert [p.read_bytes() for p in warm.files][-1] == b"Context 1"
    assert [p.name for p in warm.files] == ["0001.txt", "0002.txt", "0003.txt", "0004.txt", "Context.md"]
    assert warm.is_current()
    (folder / "0001.txt").write_bytes(b"changed!")
    assert not warm.is_current()
    with pytest.raises(ValueError, match="เปลี่ยน"):
        prepare_cached_bundle(source, group, (attachment,), tmp_path / "cache", **kwargs)


def test_cache_change_context_or_manifest_never_reuses_stale_files(tmp_path):
    _, source = _source(tmp_path)
    group = translation_groups(source, 4)[0]
    ref = tmp_path / "Prompt.md"
    ref.write_bytes(b"one")
    args = dict(identity="one", revision="rev", batch_size=4)
    first = prepare_cached_bundle(source, group, (ref,), tmp_path / "cache", **args)
    ref.write_bytes(b"two 2")
    assert not first.is_current()
    next_bundle = prepare_cached_bundle(source, group, (ref,), tmp_path / "cache", **args)
    assert next_bundle.cache_entry != first.cache_entry
    manifest = next_bundle.cache_entry / "manifest.json"
    manifest.write_text('{"bad": 1}', encoding="utf-8")
    again = prepare_cached_bundle(source, group, (ref,), tmp_path / "cache", **args)
    assert not again.timings["cache_hit"]
    assert again.cache_entry != next_bundle.cache_entry


def test_cache_pins_last_clipboard_and_does_not_delete_recent_entries(tmp_path):
    _, source = _source(tmp_path)
    bundle = prepare_cached_bundle(
        source, translation_groups(source, 4)[0], (), tmp_path / "cache",
        identity="source", revision="rev", batch_size=4)
    pin_clipboard_bundle(tmp_path / "cache", bundle)
    assert cleanup_translation_cache(tmp_path / "cache", max_bytes=1) == 0
    assert all(path.exists() for path in bundle.files)


def test_zip_cache_contains_only_expected_chapters_and_references(tmp_path):
    from zipfile import ZipFile
    _, source = _source(tmp_path)
    group = translation_groups(source, 4)[1]
    ref = tmp_path / "Glossary.txt"
    ref.write_bytes(b"glossary")
    bundle = prepare_cached_bundle(
        source, group, (ref,), tmp_path / "cache",
        identity="source", revision="rev", batch_size=4, as_zip=True)
    archive, = bundle.files
    with ZipFile(archive) as z:
        assert z.namelist() == [
            "source/0005.txt", "source/0006.txt", "source/0007.txt",
            "source/0008.txt", "references/Glossary.txt",
        ]
        assert z.read("references/Glossary.txt") == b"glossary"


def test_index_history_handles_548_groups_and_repeated_events(tmp_path):
    _, source = _source(tmp_path, count=548)
    groups = translation_groups(source, 1)
    events = []
    for i in range(1, 1001):
        events.append({
            "source_identity": "one", "source_revision": "rev",
            "start": i % 548 + 1, "end": i % 548 + 1,
            "chapter_numbers": [i % 548 + 1],
        })
    t = perf_counter()
    statuses = index_group_copy_status(events, identity="one", revision="rev", groups=groups)
    elapsed = perf_counter() - t
    assert len(statuses) == 548
    assert statuses[1] == "copied" and statuses[548] == "copied"
    assert elapsed >= 0  # Performance is reported, never asserted against runner speed.


def test_page_ready_copy_and_repeat_keep_clipboard_and_scroll(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path / "repo")
    profile = NovelProfile()
    folder, _ = _source(tmp_path)
    page = TranslationBatchPage(
        repo, lambda: profile, object(),
        {"mode": "folder", "path": str(folder), "size": 4},
        lambda _state: None, lambda: None)
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        worker = page._copy_worker
        if worker is not None:
            assert worker.wait(20000)
            app.processEvents()
        first = page._groups[0]
        assert first.index in page._ready_bundles
        for i in range(2):
            page.copy_group(first, page.findChild(QPushButton, "translationBatchCopy1"))
            app.processEvents()
            assert "สำเร็จ" in page.summary.text()
            assert len(app.clipboard().mimeData().urls()) == 4
            assert page._group_status(first) == "copied"
        from novel_workflow.batch_copy_history import load_history
        assert len(load_history(repo, profile.id, "translation")) == 2
    finally:
        if page._copy_worker is not None:
            page._copy_worker.wait(20000)
        page.close()
