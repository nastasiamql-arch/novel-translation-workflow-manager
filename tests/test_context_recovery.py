from __future__ import annotations

import pytest

from novel_workflow.recovery import (
    BACKUP_LIMIT,
    backup_file,
    backup_matches_context,
    commit_staged,
    context_chapter_range,
    list_backups,
    restore_backup,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("บทที่ 10\nเนื้อหา", "10"),
        ("Chapter 101-105\nเนื้อหา", "101-105"),
        ("第1章\n内容", "1"),
        ("第1-5章\n内容", "1-5"),
        ("บทที่ 1\nบทที่ 2\nบทที่ 3\nบทที่ 4\nบทที่ 5", "1-5"),
        ("บทที่ 1\nบทที่ 3\nบทที่ 5", None),
        ("มีเลข 1 และ 5 ในประโยคธรรมดา", None),
        ("# Examples\nChapter 1\nChapter 2", None),
        ("# Chapter Progress\nChapter 1\nChapter 2\n\n# Examples\nChapter 20", "1-2"),
        ("# Chapter Progress\nChapter 1\n\n# Notes\nChapter 2", "1"),
    ],
)
def test_context_chapter_range_uses_contiguous_progress_evidence(text, expected):
    assert context_chapter_range(text.encode("utf-8")) == expected


def test_human_backups_are_unique_safe_and_readable(tmp_path):
    context = tmp_path / "Context.md"
    context.write_bytes(b"old")
    options = {
        "display_name": "CON",
        "metadata": {"chapter_range": "1-5", "profile_id": "profile-a"},
    }

    first = backup_file(context, **options)
    second = backup_file(context, **options)

    assert first != second
    assert first.name.startswith("_CON 1-5_")
    assert " 1-5_" in first.name
    assert len(first.name) < 140
    assert first.read_bytes() == second.read_bytes() == b"old"
    assert len(list_backups(context)) == 2


def test_human_backup_sanitizes_and_truncates_translator_stem(tmp_path):
    context = tmp_path / "Context.md"
    context.write_bytes(b"old")

    backup = backup_file(
        context,
        display_name="Works:*?\"Tag" + "作品" * 100,
        metadata={"chapter_range": None},
    )

    assert ":" not in backup.name and "*" not in backup.name and "?" not in backup.name
    assert '"' not in backup.name
    assert len(backup.name) < 120


def test_human_backup_truncation_counts_windows_unicode_path_units(tmp_path):
    context = tmp_path / "Context.md"
    context.write_bytes(b"old")

    backup = backup_file(
        context,
        display_name="Novel" + "😀" * 100,
        metadata={"chapter_range": "1-5"},
    )

    assert len(str(backup).encode("utf-16-le")) // 2 <= 240


def test_hash_and_human_backups_restore_and_stay_bound_to_context(tmp_path):
    context = tmp_path / "Context.md"
    context.write_bytes(b"legacy snapshot")
    legacy = backup_file(context)
    context.write_bytes(b"human snapshot")
    human = backup_file(
        context,
        display_name="WorksTranslator",
        metadata={"profile_id": "profile-a", "chapter_range": "101-105"},
    )

    assert set(list_backups(context)) == {legacy, human}
    assert set(list_backups(context, profile_id="profile-a")) == {legacy, human}
    assert list_backups(context, profile_id="profile-b") == [legacy]
    assert backup_matches_context(context, legacy)
    assert backup_matches_context(context, human)
    restore_backup(context, legacy)
    assert context.read_bytes() == b"legacy snapshot"
    restore_backup(context, human)
    assert context.read_bytes() == b"human snapshot"
    with pytest.raises(OSError, match="ไม่ได้ผูก"):
        restore_backup(context, human, profile_id="profile-b")

    other = tmp_path / "OtherContext.md"
    other.write_bytes(b"other")
    assert list_backups(other) == []
    with pytest.raises(OSError, match="ไม่ได้ผูก"):
        restore_backup(other, human)


def test_combined_backup_limit_prunes_only_oldest_backup_for_document(tmp_path):
    context = tmp_path / "Context.md"
    other = tmp_path / "Other.md"
    context.write_bytes(b"snapshot")
    other.write_bytes(b"other")
    legacy = [backup_file(context) for _ in range(BACKUP_LIMIT)]
    other_backup = backup_file(other)
    human = backup_file(
        context,
        display_name="NovelTranslator",
        metadata={"chapter_range": "1-5"},
    )

    backups = list_backups(context)
    assert len(backups) == BACKUP_LIMIT
    assert human in backups
    assert legacy[0] not in backups
    assert not legacy[0].exists()
    assert other_backup.exists()


def test_backup_metadata_failure_keeps_context_and_removes_partial_backup(tmp_path, monkeypatch):
    import novel_workflow.recovery as recovery

    context = tmp_path / "Context.md"
    context.write_bytes(b"old bytes")
    staged = tmp_path / "staged"
    staged.write_bytes(b"new bytes")
    real_replace = recovery.os.replace

    def fail_metadata(source, destination):
        if str(destination).endswith(".bak.meta"):
            raise OSError("metadata write failed")
        return real_replace(source, destination)

    monkeypatch.setattr(recovery.os, "replace", fail_metadata)
    with pytest.raises(OSError, match="metadata write failed"):
        commit_staged(
            [(context, staged)],
            backup_options={context.resolve(): {
                "display_name": "NovelTranslator",
                "metadata": {"chapter_range": "1-5"},
            }},
        )

    assert context.read_bytes() == b"old bytes"
    assert list((tmp_path / ".palantir-recovery").glob("*.bak")) == []


def test_context_replace_failure_keeps_original_and_recovery_copy(tmp_path, monkeypatch):
    import novel_workflow.recovery as recovery

    context = tmp_path / "Context.md"
    context.write_bytes(b"old bytes")
    staged = tmp_path / "staged"
    staged.write_bytes(b"new bytes")
    monkeypatch.setattr(
        recovery,
        "replace_with_retry",
        lambda *_args: (_ for _ in ()).throw(OSError("replace failed")),
    )

    with pytest.raises(OSError, match="replace failed"):
        commit_staged(
            [(context, staged)],
            backup_options={context.resolve(): {
                "display_name": "NovelTranslator",
                "metadata": {"chapter_range": "1-5"},
            }},
        )

    assert context.read_bytes() == b"old bytes"
    assert list_backups(context)[0].read_bytes() == b"old bytes"


def test_transaction_without_backup_artifacts_rolls_back_both_files(tmp_path):
    context = tmp_path / "Context.md"
    export = tmp_path / "Translator 1.txt"
    context.write_bytes(b"old context")
    staged_context = tmp_path / "context.stage"
    staged_export = tmp_path / "export.stage"
    staged_context.write_bytes(b"new translator")
    staged_export.write_bytes(b"new translator")

    with pytest.raises(OSError, match="verification failed"):
        commit_staged(
            [(export, staged_export), (context, staged_context)],
            commit_metadata=lambda: (_ for _ in ()).throw(OSError("verification failed")),
            create_backups=False,
            no_overwrite=(export,),
        )

    assert not export.exists()
    assert context.read_bytes() == b"old context"
    assert not list(tmp_path.glob("*.transaction-recovery"))
    assert not list(tmp_path.glob("*.bak"))
    assert not list(tmp_path.glob("*.bak.meta"))


def test_transaction_rollback_failure_preserves_and_reports_recovery_file(tmp_path, monkeypatch):
    import novel_workflow.recovery as recovery

    context = tmp_path / "Context.md"
    export = tmp_path / "Translator 1.txt"
    context.write_bytes(b"old context")
    staged_context = tmp_path / "context.stage"
    staged_export = tmp_path / "export.stage"
    staged_context.write_bytes(b"new translator")
    staged_export.write_bytes(b"new translator")
    real_replace = recovery.replace_with_retry

    def fail_restore(source, destination):
        if str(source).endswith(".transaction-recovery"):
            raise OSError("rollback denied")
        return real_replace(source, destination)

    monkeypatch.setattr(recovery, "replace_with_retry", fail_restore)
    with pytest.raises(OSError, match="rollback denied") as error:
        commit_staged(
            [(export, staged_export), (context, staged_context)],
            commit_metadata=lambda: (_ for _ in ()).throw(OSError("verification failed")),
            create_backups=False,
            no_overwrite=(export,),
        )

    snapshots = list(tmp_path.glob("*.transaction-recovery"))
    assert len(snapshots) == 1
    assert snapshots[0].read_bytes() == b"old context"
    assert str(snapshots[0]) in str(error.value)
    assert not export.exists()
