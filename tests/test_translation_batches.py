"""Translation batch contracts and regressions."""
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from novel_workflow.translation_batches import (
    find_translation_groups, load_translation_source, translation_groups,
    validate_translation_source,
)
from novel_workflow.translation_batch_clipboard import prepare_translation_batch
from novel_workflow.translation_source_binding import (
    TranslationAttachment, translation_reference_files, translation_step,
)
from novel_workflow.models import AppSettings, WorkflowStep, NovelProfile


def novel_text(start, count, newline="\n"):
    return "".join(f"第{i}章 标题{newline}正文 {i}{newline}{newline}" for i in range(start, start+count))


@pytest.mark.parametrize("count", [5, 30, 100, 1000])
def test_pasted_ranges(count):
    text = novel_text(1, count)
    source = load_translation_source("paste", text=text)
    groups = translation_groups(source, 5)
    assert len(source.chapters) == count
    assert len(groups) == count // 5
    assert b"".join(c.content for c in source.chapters).decode() == text


def test_high_numbers_and_lookup():
    source = load_translation_source("paste", text=novel_text(601, 20))
    groups = translation_groups(source)
    assert [(g.start, g.end) for g in groups] == [(601, 605), (606, 610), (611, 615), (616, 620)]
    assert find_translation_groups(groups, "603") == (groups[0],)
    assert find_translation_groups(groups, "606-610") == (groups[1],)


def test_text_preserves_crlf_and_blank_lines():
    text = novel_text(1, 5, "\r\n")
    source = load_translation_source("paste", text=text)
    assert b"".join(c.content for c in source.chapters) == text.encode()


def test_missing_and_duplicate():
    source = load_translation_source("paste", text=novel_text(6, 2) + novel_text(9, 2))
    group = translation_groups(source)[0]
    assert group.missing == (8,)
    with pytest.raises(ValueError, match="ซ้ำ"):
        load_translation_source("paste", text=novel_text(1, 2) + novel_text(2, 1))
    with pytest.raises(ValueError, match="ก่อนหัวบทแรก"):
        load_translation_source("paste", text="ห้ามทิ้งข้อมูล\n" + novel_text(1, 2))


def test_resplit_does_not_destroy_source():
    source = load_translation_source("paste", text=novel_text(1, 30))
    assert len(translation_groups(source, 5)) == 6
    assert len(translation_groups(source, 10)) == 3
    assert len(source.chapters) == 30


def test_folder_numbers_and_bytes(tmp_path):
    folder = tmp_path / "source"
    folder.mkdir()
    for number in [3, 1, 2]:
        (folder / f"{number:04d} 中文.txt").write_bytes(f"第{number}章\r\n正文\r\n".encode())
    src = load_translation_source("folder", path=folder)
    assert [c.number for c in src.chapters] == [1, 2, 3]
    output = prepare_translation_batch(src, translation_groups(src)[0], (), tmp_path / "cache")
    assert [p.read_bytes() for p in output] == [
        (folder / f"{i:04d} 中文.txt").read_bytes() for i in [1, 2, 3]
    ]
    (folder / "0004 中文.txt").write_text("content")
    with pytest.raises(ValueError, match="รีเฟรช"):
        validate_translation_source(src)


def test_combined_only_selected_chapters_and_refs(tmp_path):
    combined = tmp_path / "FATE.txt"
    combined.write_text(novel_text(1, 100), encoding="utf-8")
    reference = tmp_path / "Glossary.md"
    reference.write_text("กลอสซารี", encoding="utf-8")
    original = combined.read_bytes()
    src = load_translation_source("file", path=combined)
    batch = translation_groups(src)[1]
    archive, = prepare_translation_batch(
        src, batch, (reference,), tmp_path / "cache", as_zip=True)
    with ZipFile(archive) as zip_file:
        names = zip_file.namelist()
        assert len(names) == 6
        assert "references/Glossary.md" in names
        assert "source/0006 标题.txt" in names
        assert "FATE.txt" not in str(names)
        assert zip_file.testzip() is None
    assert combined.read_bytes() == original
    assert [c.number for c in src.chapters] == list(range(1, 101))


def test_references_translation_only(tmp_path):
    glossary = tmp_path / "Glossary.md"
    glossary.write_text("prompt")
    source = tmp_path / "FATE.txt"
    source.write_text(novel_text(1, 4), encoding="utf-8")
    entries = (TranslationAttachment("source", "Source", source),
               TranslationAttachment("ref", "Glossary", glossary))
    assert translation_reference_files(entries, source, "source") == (glossary.resolve(),)


def test_source_changed_before_copy_preserves_clipboard(tmp_path):
    src_file = tmp_path / "FATE.txt"
    src_file.write_text(novel_text(1, 5), encoding="utf-8")
    source = load_translation_source("file", path=src_file)
    src_file.write_text(novel_text(1, 6), encoding="utf-8")
    with pytest.raises(ValueError, match="รีเฟรช"):
        prepare_translation_batch(source, translation_groups(source)[0], (), tmp_path / "cache")
    assert not list((tmp_path / "cache").rglob("*.zip"))


def test_paste_preview_invalidation():
    text = novel_text(1, 5)
    src = load_translation_source("paste", text=text)
    with pytest.raises(ValueError, match="Preview"):
        validate_translation_source(src, text=text + "เนื้อหาเพิ่ม")


def test_profile_preferences_are_separate():
    settings = AppSettings()
    settings.translation_batch_profiles["a"] = {"zip": True, "size": 5}
    settings.translation_batch_profiles["b"] = {"zip": False, "size": 10}
    assert settings.translation_batch_profiles["a"]["zip"]
    assert not settings.translation_batch_profiles["b"]["zip"]
    assert not settings.copy_files_as_zip
    assert not settings.history_copy_as_zip


def test_translation_step_strict():
    profile = NovelProfile()
    assert translation_step(profile).name == "แปล"
    profile.workflow.steps.append(WorkflowStep(name="แปล"))
    with pytest.raises(ValueError):
        translation_step(profile)


def test_selected_folder_copy_does_not_rehash_all_unselected_chapters(tmp_path, monkeypatch):
    """Validate every filename/metadata, but hash copied chapters only."""
    import novel_workflow.translation_batches as batch_module
    source_folder = tmp_path / "source"
    source_folder.mkdir()
    for number in range(1, 101):
        (source_folder / f"{number:04d}.txt").write_text(
            f"第{number}章\\n正文", encoding="utf-8")
    source = load_translation_source("folder", path=source_folder)
    group = translation_groups(source, 3)[0]
    digested = []
    real_digest = batch_module.file_digest
    def counted(path):
        digested.append(Path(path).name)
        return real_digest(path)
    monkeypatch.setattr(batch_module, "file_digest", counted)
    output = prepare_translation_batch(source, group, (), tmp_path / "cache")
    assert len(output) == 3
    assert set(digested) == {"0001.txt", "0002.txt", "0003.txt"}
    assert all(p.read_bytes() == (source_folder / p.name).read_bytes() for p in output)
    # A changed unselected chapter must still invalidate a source snapshot.
    (source_folder / "0099.txt").write_text("changed content", encoding="utf-8")
    with pytest.raises(ValueError, match="เปลี่ยน"):
        prepare_translation_batch(source, group, (), tmp_path / "another")


def test_strict_validation_detects_same_mtime_content_change(tmp_path):
    import os
    source_folder = tmp_path / "chapters"
    source_folder.mkdir()
    chapter = source_folder / "0001.txt"
    chapter.write_text("第1章\\nAAA", encoding="utf-8")
    source = load_translation_source("folder", path=source_folder)
    state = chapter.stat()
    chapter.write_text("第1章\\nBBB", encoding="utf-8")
    os.utime(chapter, ns=(state.st_atime_ns, state.st_mtime_ns))
    # Even if modification time is restored, strict validation re-hashes.
    with pytest.raises(ValueError, match="เปลี่ยน"):
        validate_translation_source(source)
