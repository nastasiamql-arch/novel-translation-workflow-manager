"""Migration and independent clipboard ZIP preferences."""
from novel_workflow.storage import ProjectRepository


def test_upgrade_migrates_combined_zip_preference_to_history_only(tmp_path):
    repo = ProjectRepository(tmp_path / 'data')
    repo.settings_path.write_text('{"copy_files_as_zip": true}', encoding='utf-8')
    settings = repo.load_settings()
    assert settings.history_copy_as_zip is True
    assert settings.copy_files_as_zip is False
    assert settings.history_zip_migrated is True
    assert repo.load_settings() == settings


def test_workflow_zip_remains_independent_after_migration(tmp_path):
    repo = ProjectRepository(tmp_path / 'data')
    settings = repo.load_settings()
    assert settings.history_copy_as_zip is False
    assert settings.copy_files_as_zip is False
    settings.copy_files_as_zip = True
    repo.save_settings(settings)
    loaded = repo.load_settings()
    assert loaded.copy_files_as_zip is True
    assert loaded.history_copy_as_zip is False
    loaded.history_copy_as_zip = True
    repo.save_settings(loaded)
    final = repo.load_settings()
    assert final.copy_files_as_zip is True
    assert final.history_copy_as_zip is True
