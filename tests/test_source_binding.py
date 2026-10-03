from novel_workflow.models import NovelProfile, NovelSourceBinding
from novel_workflow.storage import ProjectRepository, read_json, write_json


def test_legacy_profile_without_binding_migrates_in_memory(tmp_path):
    repo = ProjectRepository(tmp_path)
    folder = repo.profile_dir("a" * 32)
    folder.mkdir(parents=True)
    write_json(folder / "profile.json", {"id": "a" * 32, "name": "Legacy", "unknown_legacy_value": "preserve"})
    loaded = repo.list_profiles()[0]
    assert loaded.name == "Legacy" and loaded.source_binding is None
    migrated = read_json(folder / "profile.json", {})
    assert migrated["schema_version"] == 6 and migrated["unknown_legacy_value"] == "preserve"


def test_binding_roundtrip(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(id="b" * 32, source_binding=NovelSourceBinding("tomatomtl", "https://tomatomtl.com/book/1", "1"))
    repo.save_profile(profile)
    loaded = repo.list_profiles()[0]
    assert loaded.source_binding.remote_book_id == "1"
    assert loaded.source_binding.content_mode == "raw_zh"
