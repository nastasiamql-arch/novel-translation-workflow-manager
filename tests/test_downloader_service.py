import json

from novel_workflow.downloader.models import BookInfo, ChapterContent, ChapterInfo
from novel_workflow.downloader.registry import SourceRegistry
from novel_workflow.downloader.service import DownloadService
from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository


class FakeSource:
    id = "fake"
    name = "Fake"
    domains = ("example.test",)
    def __init__(self): self.downloaded = []; self.book_id = "book"
    def can_handle(self, url): return "example.test" in url
    def extract_book_id(self, url): return "book"
    def get_book(self, url): return BookInfo(self.id, self.book_id, url, "Novel", total_chapters=3)
    def get_chapters(self, book): return [ChapterInfo(f"id-{i}", i, f"第{i}章", f"https://example.test/{i}") for i in range(1, 4)]
    def get_chapter(self, chapter, mode="raw_zh"):
        self.downloaded.append(chapter.index)
        return ChapterContent(chapter.remote_id, chapter.index, chapter.title, f"原文 {chapter.index}")


def setup(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(id="f" * 32)
    repo.save_profile(profile)
    source = FakeSource()
    service = DownloadService(repo, SourceRegistry([source]))
    service.bind(profile, "https://example.test/book")
    return repo, profile, source, service


def test_range_manifest_skip_resume_and_missing_repair(tmp_path):
    repo, profile, source, service = setup(tmp_path)
    first = service.download_range(profile, 1, 2)
    assert first.downloaded == 2
    assert sorted(p.name for p in (repo.profile_dir(profile.id) / "source").glob("*.txt")) == ["0001 第1章.txt", "0002 第2章.txt"]
    resumed = service.download_updates(profile)
    assert resumed.downloaded == 1 and source.downloaded == [1, 2, 3]
    skip = service.download_updates(profile)
    assert skip.downloaded == 0 and source.downloaded == [1, 2, 3]
    (repo.profile_dir(profile.id) / "source" / "0002 第2章.txt").unlink()
    repaired = service.download_updates(profile)
    assert repaired.downloaded == 1 and source.downloaded[-1] == 2


def test_check_updates_uses_remote_ids(tmp_path):
    repo, profile, source, service = setup(tmp_path)
    service.download_range(profile, 1, 2)
    result = service.check_updates(profile)
    assert [chapter.remote_id for chapter in result["missing"]] == ["id-3"]
    assert result["downloaded"] == 2


def test_selected_range_overwrite_is_explicit(tmp_path):
    repo, profile, source, service = setup(tmp_path)
    service.download_range(profile, 1, 1)
    target = repo.profile_dir(profile.id) / "source" / "0001 第1章.txt"
    target.write_text("manual edit", encoding="utf-8")
    skipped = service.download_range(profile, 1, 1)
    assert skipped.skipped == 1 and target.read_text(encoding="utf-8") == "manual edit"
    overwritten = service.download_range(profile, 1, 1, skip_existing=False, overwrite=True)
    assert overwritten.downloaded == 1 and target.read_text(encoding="utf-8") == "原文 1"


def test_rebinding_archives_old_manifest_without_reusing_remote_ids(tmp_path):
    repo, profile, source, service = setup(tmp_path)
    service.download_range(profile, 1, 1)
    source.book_id = "new-book"
    book = source.get_book("https://example.test/new-book")
    service.bind(profile, book.url, book, source)
    meta = repo.profile_dir(profile.id) / "source_meta"
    assert (meta / "manifest.fake.book.json").exists()
    assert json.loads((meta / "manifest.json").read_text(encoding="utf-8"))["chapters"] == {}
