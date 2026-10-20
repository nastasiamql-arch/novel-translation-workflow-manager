"""Regression contract: web novel downloading was removed in v4."""
from pathlib import Path
from dataclasses import asdict

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository


def test_profile_removal_preserves_source_and_translation_files(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="Chinese Novel")
    repo.save_profile(profile)
    folder = repo.profile_dir(profile.id)
    source = folder / "source" / "FATE.txt"
    source.write_text("第一章 原文", encoding="utf-8")
    translator = folder / "translated" / "FATETranslator.txt"
    translator.write_text("บทที่ 1 ฉบับแปล", encoding="utf-8")
    profile_path = folder / "profile.json"
    import json
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    data["source_binding"] = {
        "source_id": "tomatomtl", "book_url": "https://example.invalid",
        "remote_book_id": "original"
    }
    profile_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    restored = repo.list_profiles()[0]
    assert restored.name == "Chinese Novel"
    assert "source_binding" not in asdict(restored)
    updated = json.loads(profile_path.read_text(encoding="utf-8"))
    assert "source_binding" not in updated
    backup = folder / "profile.json.pre-v4-upgrade.bak"
    assert json.loads(backup.read_text(encoding="utf-8"))["source_binding"] == data["source_binding"]
    assert source.read_text(encoding="utf-8") == "第一章 原文"
    assert translator.read_text(encoding="utf-8") == "บทที่ 1 ฉบับแปล"
    before = backup.read_bytes()
    restored.name = "After upgrade"
    repo.save_profile(restored)
    assert backup.read_bytes() == before
    assert "source_binding" not in json.loads(profile_path.read_text(encoding="utf-8"))


def test_deprecated_downloader_not_in_ui_or_dependencies():
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parents[1]
    assert not (root / "src/novel_workflow/downloader").exists()
    assert not (root / "src/novel_workflow/downloader_ui").exists()
    from novel_workflow.shell_components import NavigationSidebar
    sidebar = NavigationSidebar()
    assert "downloader" not in sidebar.buttons
    assert set(sidebar.buttons) == {"library", "workspace", "progress", "groups", "settings", "novel-inspector"}
    assert "playwright" not in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "downloader" not in (root / "src/novel_workflow/workspace_window.py").read_text(encoding="utf-8").lower().replace("download_update","").replace("_update_download","").replace("finished_download","")
