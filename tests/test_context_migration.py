import json
import os
from datetime import datetime
from pathlib import Path

from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_progress import daily_chapter_count, local_day, sync_profile_context


def test_import_migrates_launcher_context_and_checkpoint_for_daily_delta(tmp_path):
    context = tmp_path / "NovelContext.md"
    context.write_text("บทที่ 125\nบทที่ 130\n", encoding="utf-8")
    modified = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    timestamp = modified.timestamp()
    os.utime(context, (timestamp, timestamp))

    source = tmp_path / "launcher.json"
    source.write_text(json.dumps({
        "novels": [{
            "id": "launcher-novel",
            "name": "Novel A",
            "mainFolder": str(tmp_path),
            "contextPath": None,
            "files": [{"name": context.name, "path": str(context), "enabled": True}],
        }],
        "groups": [],
        "translationStats": {
            "checkpoints": [{
                "novelId": "launcher-novel",
                "contextPath": str(context),
                "latestChapter": 125,
                "observedAt": "2026-09-26T12:00:00+00:00",
            }],
            "days": [],
        },
    }), encoding="utf-8")

    repo = ProjectRepository(tmp_path / "app")
    repo.import_launcher_config(source)
    profile = repo.list_profiles()[0]

    assert profile.context_path == str(context.resolve())
    assert profile.translation_checkpoint_path == os.path.normcase(str(context.resolve()))
    assert profile.chapter_state.current_chapter == 125

    assert sync_profile_context(profile)
    assert profile.chapter_state.current_chapter == 130
    assert daily_chapter_count(profile, local_day(timestamp)) == 5

    repo.save_profile(profile)
    repo.import_launcher_config(source)
    reloaded = repo.list_profiles()[0]
    assert reloaded.chapter_state.current_chapter == 130
    assert not sync_profile_context(reloaded)
    assert daily_chapter_count(reloaded, local_day(timestamp)) == 5
