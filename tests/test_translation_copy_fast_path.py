"""Stage 1 fast-path regressions; no novel files outside tmp_path are touched."""
from __future__ import annotations
import hashlib
from zipfile import ZipFile
import pytest
from novel_workflow.translation_batches import (
    fast_folder_snapshot, load_translation_source, translation_groups,
    validate_translation_source,
)
from novel_workflow.vocabulary_batches import scan_chapter_files
from novel_workflow.translation_clipboard_cache import prepare_cached_bundle


def _source(tmp_path, count=1600):
    folder = tmp_path / "WebNovel" / "Volume"
    folder.mkdir(parents=True)
    for number in range(1, count + 1):
        (folder / f"{number:04d}.txt").write_bytes(
            f"第{number}章\n".encode() + b"original data " * 460)
    return folder, load_translation_source("folder", path=folder)


def _cached(source, group, directory, references=(), *, as_zip=False):
    return prepare_cached_bundle(
        source, group, references, directory,
        identity="fixture", revision="fixture-revision", batch_size=3, as_zip=as_zip)


def test_snapshot_matches_chapter_scanner_and_duplicate_error(tmp_path):
    folder = tmp_path / "chapters"
    folder.mkdir()
    for name in ("0001.txt", "0002_title.TXT", "003-标题.txt", "notes.md",
                 "no_number.txt", "1x.txt", "1000.txt"):
        (folder / name).write_text(name, encoding="utf-8")
    observed = fast_folder_snapshot(folder)
    expected = scan_chapter_files(folder)
    assert [(number, path) for number, path, _ in observed] == [
        (chapter.number, chapter.path) for chapter in expected]
    for _, path, signature in observed:
        st = path.stat()
        assert signature == (st.st_size, st.st_mtime_ns, st.st_ctime_ns)
    (folder / "1.txt").write_text("duplicate", encoding="utf-8")
    with pytest.raises(ValueError, match="ซ้ำ"):
        fast_folder_snapshot(folder)


def test_1600_files_cold_and_hit_bound_checks(tmp_path, monkeypatch):
    import novel_workflow.translation_batches as batch
    import novel_workflow.translation_batch_clipboard as clipboard
    import novel_workflow.translation_clipboard_cache as cache
    _, source = _source(tmp_path)
    group = translation_groups(source, 3)[0]
    counters = {"check": 0, "validate": 0}
    original_check, original_validate = batch._check_path, batch.validate_translation_source

    def counted_check(*args, **kwargs):
        counters["check"] += 1
        return original_check(*args, **kwargs)

    def counted_validate(*args, **kwargs):
        counters["validate"] += 1
        return original_validate(*args, **kwargs)

    for module in (batch, clipboard, cache):
        monkeypatch.setattr(module, "_check_path", counted_check)
        monkeypatch.setattr(module, "validate_translation_source", counted_validate)
    for expected_hit in (False, True):
        counters.update(check=0, validate=0)
        ready = _cached(source, group, tmp_path / "cache")
        assert ready.timings["cache_hit"] is expected_hit
        assert counters["check"] <= 50, counters
        assert counters["validate"] <= 2, counters
        assert ready.is_current()


@pytest.mark.parametrize("operation", ("add", "delete", "rename"))
def test_folder_listing_change_requires_refresh(tmp_path, operation):
    folder, source = _source(tmp_path, 8)
    if operation == "add":
        (folder / "0009.txt").write_bytes(b"new")
    elif operation == "delete":
        (folder / "0008.txt").unlink()
    else:
        (folder / "0008.txt").rename(folder / "0010.txt")
    with pytest.raises(ValueError, match="รีเฟรช"):
        validate_translation_source(source, selected_paths=(folder / "0001.txt",))


def test_unselected_file_change_rejected_before_publish(tmp_path):
    folder, source = _source(tmp_path, 9)
    group = translation_groups(source, 3)[0]
    ready = _cached(source, group, tmp_path / "cache")
    (folder / "0009.txt").write_bytes(b"edited unselected chapter")
    assert ready.files
    with pytest.raises(ValueError, match="รีเฟรช"):
        validate_translation_source(source, selected_paths=(folder / "0001.txt",))


def test_changed_glossary_never_reuses_stale_bundle(tmp_path):
    _, source = _source(tmp_path, 6)
    group = translation_groups(source, 3)[0]
    ref = tmp_path / "Glossary.md"
    ref.write_bytes(b"OLD")
    first = _cached(source, group, tmp_path / "cache", (ref,))
    ref.write_bytes(b"NEW")
    assert not first.is_current()
    fresh = _cached(source, group, tmp_path / "cache", (ref,))
    assert fresh.cache_entry != first.cache_entry
    assert fresh.files[-1].read_bytes() == b"NEW"


@pytest.mark.parametrize("as_zip", (False, True))
def test_copied_file_and_zip_bytes_exact(tmp_path, as_zip):
    folder, source = _source(tmp_path, 9)
    group = translation_groups(source, 3)[1]
    refs = []
    for number in range(5):
        ref = tmp_path / f"Context_{number}.md"
        ref.write_bytes(bytes([number]) * 1000)
        refs.append(ref)
    originals = [*(folder / f"{i:04d}.txt" for i in (4, 5, 6)), *refs]
    original_hashes = [hashlib.sha256(path.read_bytes()).digest() for path in originals]
    bundle = _cached(source, group, tmp_path / "cache", refs, as_zip=as_zip)
    if as_zip:
        with ZipFile(bundle.files[0]) as archive:
            members = [*(f"source/{path.name}" for path in originals[:3]),
                       *(f"references/{path.name}" for path in refs)]
            assert archive.namelist() == members
            copied = [archive.read(member) for member in members]
    else:
        copied = [path.read_bytes() for path in bundle.files]
    assert [hashlib.sha256(data).digest() for data in copied] == original_hashes
    assert [hashlib.sha256(path.read_bytes()).digest() for path in originals] == original_hashes


def test_symlink_rejected_even_when_txt_name_is_unnumbered(tmp_path):
    folder = tmp_path / "chapters"
    folder.mkdir()
    target = tmp_path / "real.txt"
    target.write_bytes(b"original")
    try:
        (folder / "unrelated.txt").symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    with pytest.raises(ValueError, match="Symbolic links and junctions"):
        fast_folder_snapshot(folder)
