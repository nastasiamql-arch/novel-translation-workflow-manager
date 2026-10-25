from pathlib import Path

from novel_workflow.smart_folder_scan import (
    candidates_by_role, infer_novel_code, scan_novel_folder,
)


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("sample", encoding="utf-8")
    return path


def test_scans_project_nested_unicode_and_excludes_backup(tmp_path):
    root = tmp_path / "นิยาย"
    expected = [
        _touch(root / "Project" / "ย่อย" / "IQOPrompt.md"),
        _touch(root / "Project" / "IQOStyle.docx"),
        _touch(root / "Project" / "ไกด์ไลน์การแปล.txt"),
        _touch(root / "IQOContext.md"),
        _touch(root / "IQOGlossary.csv"),
        _touch(root / "Novel (ต้นฉบับ).txt"),
    ]
    _touch(root / "Backup" / "IQOContext.md")
    _touch(root / "Recovery" / "IQOTranslator.txt")
    _touch(root / "IQOContext.md.tmp")
    files = scan_novel_folder(root)
    roles = candidates_by_role(files, "IQO")
    assert set(expected).issubset(files)
    assert [p.name for p in roles["prompt"]] == ["IQOPrompt.md"]
    assert [p.name for p in roles["style"]] == ["IQOStyle.docx"]
    assert [p.name for p in roles["guideline"]] == ["ไกด์ไลน์การแปล.txt"]
    assert [p.name for p in roles["context"]] == ["IQOContext.md"]
    assert [p.name for p in roles["glossary"]] == ["IQOGlossary.csv"]
    assert not roles["translator"]
    assert not any(path.name.endswith('.tmp') for path in files)


def test_infers_code_from_multiple_role_suffixes_without_fixed_code(tmp_path):
    paths = [_touch(tmp_path / f"WET{suffix}{ext}") for suffix, ext in (
        ("Context", ".md"), ("Glossary", ".txt"), ("Translator", ".json"),
    )]
    assert infer_novel_code(paths) == "WET"
    assert infer_novel_code(paths, "FDR") == "FDR"


def test_matches_role_names_for_multiple_novel_codes(tmp_path):
    for code in ("TQAOOP", "IQO", "WET", "FDR", "書名A"):
        paths = [_touch(tmp_path / f"{code}{suffix}{ext}") for suffix, ext in (
            ("Context", ".md"), ("Glossary", ".txt"), ("Translator", ".json"),
        )]
        roles = candidates_by_role(paths, code)
        assert len(roles["context"]) == 1
        assert len(roles["glossary"]) == 1
        assert len(roles["translator"]) == 1


def test_ambiguous_role_returns_multiple_candidates(tmp_path):
    paths = [_touch(tmp_path / folder / "TQAOOPContext.md") for folder in ("", "Project")]
    roles = candidates_by_role(paths, "TQAOOP")
    assert len(roles["context"]) == 2


def test_scan_is_bounded_and_does_not_follow_symlink(tmp_path):
    root = tmp_path / "root"
    for i in range(5):
        _touch(root / f"{i}.txt")
    outside = tmp_path / "outside"
    _touch(outside / "not-in-scan.txt")
    try:
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pass
    assert len(scan_novel_folder(root, max_files=3)) == 3
    assert all(p.name != "not-in-scan.txt" for p in scan_novel_folder(root))


def test_matcher_keeps_main_novel_distinct(tmp_path):
    paths = [_touch(tmp_path / "ABC.txt"), _touch(tmp_path / "Novel.md")]
    roles = candidates_by_role(paths, "ABC")
    assert roles["main"] == [tmp_path / "ABC.txt"]
    assert roles["novel"] == [tmp_path / "Novel.md"]
