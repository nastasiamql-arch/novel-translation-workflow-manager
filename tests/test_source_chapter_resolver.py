import pytest

from novel_workflow.models import NovelProfile
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository


@pytest.mark.parametrize(("filename", "chapter"), [
    ("0001 第一章.txt", 1), ("0012 第十二章.txt", 12), ("0128 冠军争夺战.txt", 128),
    ("chapter_12.txt", 12), ("1.txt", 1), ("12 something.txt", 12),
])
def test_resolver_supports_downloader_and_legacy_names(tmp_path, filename, chapter):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(id="c" * 32)
    profile.chapter_state.current_chapter = chapter
    folder = repo.profile_dir(profile.id) / "source"
    folder.mkdir(parents=True)
    target = folder / filename
    target.write_text("source", encoding="utf-8")
    assert AssemblyService(repo).resolve(profile, "CURRENT_SOURCE_CHAPTER") == target


@pytest.mark.parametrize(("filename", "chapter"), [("0010 chapter.txt", 1), ("112 chapter.txt", 12), ("chapter_10.txt", 1)])
def test_resolver_does_not_match_partial_numbers(tmp_path, filename, chapter):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(id="d" * 32)
    profile.chapter_state.current_chapter = chapter
    folder = repo.profile_dir(profile.id) / "source"
    folder.mkdir(parents=True)
    (folder / filename).write_text("source", encoding="utf-8")
    with pytest.raises(FileNotFoundError): AssemblyService(repo).resolve(profile, "CURRENT_SOURCE_CHAPTER")


def test_duplicate_chapter_mappings_fail_with_names(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(id="e" * 32)
    folder = repo.profile_dir(profile.id) / "source"
    folder.mkdir(parents=True)
    for name in ("0001 第一章.txt", "chapter_1.txt"):
        (folder / name).write_text("source", encoding="utf-8")
    with pytest.raises(ValueError, match="0001 第一章.txt.*chapter_1.txt"):
        AssemblyService(repo).resolve(profile, "CURRENT_SOURCE_CHAPTER")
