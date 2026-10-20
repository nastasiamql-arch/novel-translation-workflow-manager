"""Isolated inspector regressions (also run as part of the Windows CI suite)."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import zipfile
import pytest

from novel_workflow.novel_file_inspector import (
    UnsafeSource, count_characters, decode_text, inspect, list_sources,
)
from novel_workflow.novel_file_inspector_history import InspectorStore
from novel_workflow.novel_file_inspector_renumber import (
    execute_new, plan_renumber, restore_backup, execute_in_place,
)


def files(tmp_path, names, content="中" * 1600):
    root = tmp_path / "novel"
    root.mkdir()
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


@pytest.mark.parametrize("length", [0, 499, 500, 1499, 1500, 1501])
def test_character_thresholds(tmp_path, length):
    folder = files(tmp_path, ["0001.txt"], "中" * length)
    row = inspect(folder).files[0]
    assert row.count == length
    assert ("ไฟล์ว่าง" in row.reasons) == (length == 0)
    assert ("สั้นผิดปกติมาก" in row.reasons) == (0 < length < 500)
    assert ("ต่ำกว่าเกณฑ์" in row.reasons) == (500 <= length < 1500)


def test_unicode_and_bom(tmp_path):
    root = files(tmp_path, ["0001.txt"], "")
    (root / "0001.txt").write_bytes(b"\xef\xbb\xbf" + ("第十二章 开始\n" + "中" * 1501).encode())
    row = inspect(root).files[0]
    assert row.encoding == "utf-8-sig"
    assert row.heading == 12
    assert row.count == 1501
    assert "เลขหัวบทไม่ตรงกับชื่อไฟล์" in row.reasons


def test_gap_and_duplicate_numeric_names(tmp_path):
    root = files(tmp_path, ["0400.txt", "0402.txt", "0402 - copy.txt"], "")
    result = inspect(root)
    assert result.summary()["missing"] == 1
    assert any(r.virtual and r.chapter == 401 for r in result.files)
    assert len([r for r in result.files if "เลขบทซ้ำ" in r.reasons]) == 2
    with pytest.raises(ValueError, match="Ambiguous order"):
        plan_renumber(result, 400)


def test_hash_duplicate_and_non_duplicate(tmp_path):
    root = files(tmp_path, ["0001.txt", "0002.txt", "0003.txt"], "第十章 开始\n" + "中" * 2200)
    (root / "0003.txt").write_text("山川" * 1100, encoding="utf-8")
    rows = {r.name: r for r in inspect(root).files}
    assert rows["0002.txt"].duplicate_of == "0001.txt"
    assert not rows["0003.txt"].duplicate_of


def test_review_decision_persists_and_stales(tmp_path):
    root = files(tmp_path, ["0001.txt"], "中" * 20)
    state = InspectorStore(tmp_path / "state")
    first = inspect(root)
    state.mark(first, "0001.txt", "keep")
    again = inspect(root, reviews=state.reviews(root, "folder"))
    assert again.files[0].review == "keep"
    (root / "0001.txt").write_text("新" * 20, encoding="utf-8")
    changed = inspect(root, reviews=state.reviews(root, "folder"))
    assert changed.files[0].review_stale
    assert changed.files[0].review == "pending"


def test_new_result_preserves_source_and_excludes(tmp_path):
    root = files(tmp_path, [f"{n:04d}.txt" for n in range(1, 6)], "中" * 30)
    result = inspect(root)
    result.files[2].review = "excluded"
    plan = plan_renumber(result)
    target = tmp_path / "clean"
    data = (root / "0004.txt").read_bytes()
    summary = execute_new(plan, target)
    assert summary["excluded"] == 1
    assert sorted(p.name for p in target.iterdir()) == ["0001.txt", "0002.txt", "0003.txt", "0004.txt"]
    assert (target / "0003.txt").read_bytes() == data
    assert len(list(root.iterdir())) == 5
    with pytest.raises(FileExistsError):
        execute_new(plan, target)


def test_detect_modified_since_preview(tmp_path):
    root = files(tmp_path, ["0001.txt"], "中" * 1600)
    plan = plan_renumber(inspect(root))
    (root / "0001.txt").write_text("Changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        execute_new(plan, tmp_path / "new")


def test_heading_changes_only_header(tmp_path):
    root = files(tmp_path, ["0008.txt"], "第八章 开始\n第八章 出现在对话里\n" + "中" * 1600)
    # Two apparent heading lines are deliberately ambiguous; blocked.
    with pytest.raises(ValueError, match="heading"):
        plan_renumber(inspect(root), change_heading=True)
    (root / "0008.txt").write_text("第八章 开始\n她说第八章不能改，数字8也不能改。\n" + "中" * 1600, encoding="utf-8")
    plan = plan_renumber(inspect(root), start=6, change_heading=True)
    execute_new(plan, tmp_path / "new")
    text = (tmp_path / "new" / "0006.txt").read_text(encoding="utf-8")
    assert text.startswith("第六章 开始")
    assert "她说第八章不能改，数字8也不能改。" in text


def test_zip_guardrails(tmp_path):
    zip_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("../outside.txt", "危险")
    with pytest.raises(UnsafeSource):
        inspect(zip_path, "zip")
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("001.txt", "中" * 1600)
        z.writestr("001.TXT", "中" * 1600)
    with pytest.raises(UnsafeSource):
        inspect(zip_path, "zip")


def test_zip_output_nested_paths(tmp_path):
    archive = tmp_path / "novel.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("chapters/0400.txt", "中" * 1600)
        z.writestr("chapters/0401.txt", "山" * 1600)
    plan = plan_renumber(inspect(archive, "zip"), start=1)
    output = tmp_path / "renumbered.zip"
    execute_new(plan, output)
    with zipfile.ZipFile(output) as z:
        assert sorted(z.namelist()) == ["chapters/0001.txt", "chapters/0002.txt"]
    with zipfile.ZipFile(archive) as z:
        assert "chapters/0400.txt" in z.namelist()


def test_backup_and_safe_restore(tmp_path):
    root = files(tmp_path, ["0001.txt", "0002.txt"], "中" * 1600)
    original = (root / "0002.txt").read_bytes()
    result = inspect(root)
    next(r for r in result.files if r.chapter == 1).review = "excluded"
    plan = plan_renumber(result)
    operation = execute_in_place(plan, tmp_path / "backups")
    assert (root / "0001.txt").read_bytes() == original
    assert not (root / "0002.txt").exists()
    destination = tmp_path / "restored"
    restore_backup(operation["backup"], destination)
    assert (destination / "0002.txt").read_bytes() == original
    assert (destination / "0001.txt").exists()
    with pytest.raises(FileExistsError):
        restore_backup(operation["backup"], destination)


def test_incremental_cache_and_option_changes(tmp_path, monkeypatch):
    folder = files(tmp_path, ["0001.txt", "0002.txt"], "中" * 1700)
    cache = {}
    first = inspect(folder, cache=cache, options={"duplicates": False})
    assert len(cache) == 2
    import novel_workflow.novel_file_inspector as module
    def must_not_read(*args, **kwargs):
        raise AssertionError("unchanged source was re-read")
    with monkeypatch.context() as patch:
        patch.setattr(module, "read_source", must_not_read)
        again = inspect(folder, cache=cache, options={"duplicates": True})
    assert again.files[1].duplicate_of == "0001.txt"
    (folder / "0002.txt").write_text("新" * 1700, encoding="utf-8")
    changed = inspect(folder, cache=cache)
    assert changed.files[1].fingerprint != first.files[1].fingerprint


def test_zip_corrupt_file(tmp_path):
    archive = tmp_path / "broken.zip"
    archive.write_bytes(b"not a zip")
    with pytest.raises(zipfile.BadZipFile):
        inspect(archive, "zip")


def test_folder_unicode_name_numeric_sort_and_padding(tmp_path):
    root = files(tmp_path, ["10.txt", "2.txt", "1.txt"], "海" * 1510)
    plan = plan_renumber(inspect(root), start=400, padding=5)
    assert [(x.original, x.target) for x in plan.files] == [
        ("1.txt", "00400.txt"), ("2.txt", "00401.txt"), ("10.txt", "00402.txt")]


def test_backup_failure_does_not_modify_source(tmp_path, monkeypatch):
    folder = files(tmp_path, ["0001.txt", "0002.txt"], "中" * 1500)
    plan = plan_renumber(inspect(folder))
    import novel_workflow.novel_file_inspector_renumber as module
    def fail_copy(*args, **kwargs):
        raise OSError("backup copy denied")
    monkeypatch.setattr(module.shutil, "copy2", fail_copy)
    with pytest.raises(OSError):
        execute_in_place(plan, tmp_path / "backups")
    assert sorted(p.name for p in folder.iterdir()) == ["0001.txt", "0002.txt"]

def test_persistent_cache_and_history_round_trip(tmp_path):
    root = files(tmp_path, ["0400.txt"], "山" * 1800)
    store = InspectorStore(tmp_path / "state")
    cache = {}
    result = inspect(root, cache=cache)
    store.save_cache(root, "folder", cache)
    assert store.cache(root, "folder") == cache
    ident = store.add_inspection(result)
    assert store.read_inspection(ident).summary() == result.summary()
    assert store.history()[0]["id"] == ident


def test_zip_directory_entries_are_safe(tmp_path):
    archive = tmp_path / "with_dir.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("chapters/", "")
        z.writestr("chapters/0400.txt", "江" * 1555)
    assert inspect(archive, "zip").summary()["total"] == 1


def test_output_cannot_be_inside_source(tmp_path):
    root = files(tmp_path, ["0001.txt"], "山" * 1600)
    plan = plan_renumber(inspect(root))
    with pytest.raises(ValueError, match="inside"):
        execute_new(plan, root / "nested" / "output")


def test_symlink_to_other_chapter_rejected(tmp_path):
    root = files(tmp_path, ["0001.txt"], "山" * 1600)
    link = root / "0002.txt"
    try:
        link.symlink_to(root / "0001.txt")
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with pytest.raises(UnsafeSource):
        from novel_workflow.novel_file_inspector import read_source
        read_source(root, "folder", "0002.txt")
    assert inspect(root).summary()["total"] == 1


def test_failed_transaction_retains_discoverable_backup(tmp_path, monkeypatch):
    root = files(tmp_path, ["0001.txt", "0002.txt"], "海" * 1600)
    plan = plan_renumber(inspect(root))
    import novel_workflow.novel_file_inspector_renumber as module
    original_replace = module.os.replace
    def interrupted(src, dest):
        if ".novel_inspector_stage_" in str(dest):
            raise OSError("simulated interruption")
        return original_replace(src, dest)
    with monkeypatch.context() as patch:
        patch.setattr(module.os, "replace", interrupted)
        with pytest.raises(OSError, match="interruption"):
            execute_in_place(plan, tmp_path / "backups")
    journals = list((tmp_path / "backups").glob("*/journal.json"))
    assert len(journals) == 1
    assert json.loads(journals[0].read_text(encoding="utf-8"))["status"] == "recovery_required"
    restore_backup(journals[0].parent, tmp_path / "recovered")
    assert (tmp_path / "recovered" / "0002.txt").is_file()
