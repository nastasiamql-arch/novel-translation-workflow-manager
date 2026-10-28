from PySide6.QtWidgets import QPushButton
from test_polish_history_ui import window, wait_until


def test_novel_polish_navigation_removes_pending_button(window):
    w, profile, workspace, errors = window
    assert workspace.history_button.text() == 'Novel Polish'
    assert not any(b.text() == 'บันทึกไว้รอตรวจ' for b in workspace.sidebar.findChildren(QPushButton))
    workspace.history_button.click()
    wait_until(lambda: not w.history_busy())
    assert w.utility_title.text() == 'Novel Polish'
    from PySide6.QtWidgets import QLabel
    page = w._utility_pages['polish-history:' + profile.id]
    for widget in page.findChildren(QLabel) + page.findChildren(QPushButton):
        assert 'ประวัติ' not in widget.text()


def test_zip_preference_is_isolated_by_novel(window):
    w, profile, workspace, errors = window
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    page.zip_mode.setChecked(True)
    assert w.settings.history_zip_for_profile(profile.id)
    assert not w.settings.history_zip_for_profile('another-profile')
    assert w.repo.load_settings().history_zip_for_profile(profile.id)


def test_novel_polish_row_uses_real_snapshot_details_and_blue_copy_status(window):
    from PySide6.QtWidgets import QLabel
    w, profile, workspace, errors = window
    snapshot = w.polish_history.create(profile, profile.workflow.steps[1], '241-243')
    key = f'{profile.id}:{profile.polish_history_step_id}'
    w.settings.history_copy_events[key] = [{
        'snapshot_id': snapshot.manifest['snapshot_id'], 'chapter_range': '241-243',
        'timestamp': '2026-10-28T06:42:00+00:00', 'result': 'clipboard_set',
    }]
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    card = page._cards_by_id[snapshot.manifest['snapshot_id']]
    labels = card.findChildren(QLabel)
    badge = next(label for label in labels if label.text() == '✓  คัดลอกแล้ว')
    assert '#24834a' not in badge.styleSheet().lower()
    assert any('ไฟล์' in label.text() and 'MB' in label.text() for label in labels)
    assert any(label.text().startswith('คัดลอกล่าสุด ') for label in labels)
    assert page.progress_summary.text().startswith('ชุดงานทั้งหมด 1 ชุด')


def test_copied_badge_follows_theme_change(window):
    from PySide6.QtWidgets import QLabel
    w, profile, workspace, errors = window
    snapshot = w.polish_history.create(profile, profile.workflow.steps[1], '241-243')
    key = f'{profile.id}:{profile.polish_history_step_id}'
    w.settings.history_copy_events[key] = [{'snapshot_id': snapshot.manifest['snapshot_id'], 'result': 'clipboard_set'}]
    w.settings.appearance = 'Light'
    w.open_polish_history()
    wait_until(lambda: not w.history_busy())
    page = w._utility_pages['polish-history:' + profile.id]
    badge = next(label for label in page._cards_by_id[snapshot.manifest['snapshot_id']].findChildren(QLabel) if label.text() == '✓  คัดลอกแล้ว')
    assert '#20539b' in badge.styleSheet()
    w.settings.appearance = 'Dark'
    w.apply_theme()
    badge = next(label for label in page._cards_by_id[snapshot.manifest['snapshot_id']].findChildren(QLabel) if label.text() == '✓  คัดลอกแล้ว')
    assert '#91b9ff' in badge.styleSheet().lower()


def test_old_global_zip_preference_is_the_default_for_each_novel(tmp_path):
    from novel_workflow.storage import ProjectRepository
    repo = ProjectRepository(tmp_path / 'settings')
    repo.settings_path.write_text('{"history_copy_as_zip": true, "history_zip_migrated": true}', encoding='utf-8')
    settings = repo.load_settings()
    assert settings.history_zip_for_profile('old-a')
    assert settings.history_zip_for_profile('old-b')
    settings.history_copy_as_zip_by_profile['old-a'] = False
    repo.save_settings(settings)
    restored = repo.load_settings()
    assert not restored.history_zip_for_profile('old-a')
    assert restored.history_zip_for_profile('old-b')
