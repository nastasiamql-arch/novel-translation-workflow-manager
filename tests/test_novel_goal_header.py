"""Workspace-header goal regression tests; goals are per-novel and Export-based."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow
from test_release_36 import app, setup_profile


@pytest.fixture(autouse=True)
def dispose_windows():
    app()
    existing = set(QApplication.topLevelWidgets())
    yield
    for widget in set(QApplication.topLevelWidgets()) - existing:
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def select(window, profile):
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))


def confirm_chapters(profile, chapters, event_id="goal-header-export"):
    profile.translator_export_events.append({
        "event_id": event_id,
        "profile_id": profile.id,
        "status": "committed",
        "chapters": chapters,
        "local_date": date.today().isoformat(),
    })


def test_goal_is_visible_on_each_novel_header_and_updates_after_export(tmp_path):
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name="Second", translation_goal_target=3, translator_goal_baseline=0)
    first.translation_goal_target = 5
    first.translator_goal_baseline = 0
    repo.save_profile(first)
    repo.save_profile(second)
    window = MainWindow(repo)
    select(window, first)
    header = window.workspaces[first.id].novel_header

    assert "เป้าหมาย 0/5 บท" in header.goal_label.text()
    assert header.goal_bar.value() == 0
    assert not header.goal_bar.isHidden()
    assert not header.goal_reset.isHidden()

    fresh = next(p for p in repo.list_profiles() if p.id == first.id)
    confirm_chapters(fresh, list(range(1, 8)))
    repo.save_profile(fresh)
    window.refresh_translation_progress()

    assert "7/5 บท" in header.goal_label.text()
    assert "เกิน +2 บท" in header.goal_label.text()
    assert header.goal_bar.value() == 100
    assert "7/5" not in header.progress.text()  # Translator goal != Verified goal.

    select(window, second)
    other_header = window.workspaces[second.id].novel_header
    assert "เป้าหมาย 0/3 บท" in other_header.goal_label.text()
    select(window, first)
    assert "7/5 บท" in window.workspaces[first.id].novel_header.goal_label.text()


def test_header_edit_reset_cancel_and_unset_keep_export_history(tmp_path, monkeypatch):
    repo, profile, _ = setup_profile(tmp_path)
    window = MainWindow(repo)
    select(window, profile)
    header = window.workspaces[profile.id].novel_header
    assert "ยังไม่ได้ตั้งเป้าหมาย" in header.goal_label.text()
    assert header.goal_bar.isHidden()
    assert header.goal_reset.isHidden()

    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (5, True))
    header.goal_edit.click()
    assert repo.list_profiles()[0].translation_goal_target == 5
    assert "0/5 บท" in header.goal_label.text()
    assert not header.goal_reset.isHidden()

    fresh = repo.list_profiles()[0]
    confirm_chapters(fresh, [14, 15])
    repo.save_profile(fresh)
    window.refresh_translation_progress()
    assert "2/5 บท" in header.goal_label.text()

    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (100, False))
    header.goal_edit.click()
    assert repo.list_profiles()[0].translation_goal_target == 5

    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)
    header.goal_reset.click()
    assert "2/5 บท" in header.goal_label.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    header.goal_reset.click()
    saved = repo.list_profiles()[0]
    assert saved.translator_goal_baseline == 2
    assert len(saved.translator_export_events) == 1
    assert "0/5 บท" in header.goal_label.text()

    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (0, True))
    header.goal_edit.click()
    assert repo.list_profiles()[0].translation_goal_target is None
    assert header.goal_bar.isHidden()
    assert header.goal_reset.isHidden()
    assert len(repo.list_profiles()[0].translator_export_events) == 1


def test_header_goal_is_preserved_when_window_reopens(tmp_path, monkeypatch):
    repo, profile, _ = setup_profile(tmp_path)
    window = MainWindow(repo)
    select(window, profile)
    monkeypatch.setattr(QInputDialog, "getInt", lambda *args, **kwargs: (8, True))
    window.workspaces[profile.id].novel_header.goal_edit.click()
    window._close_export_reminder_accepted = True
    window.close()
    restored = MainWindow(ProjectRepository(tmp_path))
    select(restored, profile)
    assert "0/8 บท" in restored.workspaces[profile.id].novel_header.goal_label.text()
