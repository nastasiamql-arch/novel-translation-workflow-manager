from datetime import date, timedelta
import json

import pytest

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_planner import TranslationPlanner


def test_weekly_persistence_recurrence_and_precedence(tmp_path):
    repo = ProjectRepository(tmp_path)
    a, b = NovelProfile(name="A"), NovelProfile(name="B")
    repo.save_profile(a)
    repo.save_profile(b)
    planner = TranslationPlanner(repo)
    planner.path.write_text(json.dumps({"extension": {"preserved": True}}), encoding="utf-8")
    planner.save_weekly_schedule(a.id, weekdays=[0, 2, 4], target_chapters=20, caught_up=False)
    planner.save_weekly_schedule(b.id, weekdays=list(range(7)), target_chapters=10, caught_up=True)
    last_week = date(date.today().year + 1, 12, 25)
    monday = last_week + timedelta(days=(-last_week.weekday()) % 7)
    for delta in (0, 7, 14):
        assert planner.effective_weekly_plan(monday + timedelta(days=delta), a.id)["target_chapters"] == 20
        assert planner.effective_weekly_plan(monday + timedelta(days=delta), b.id)["caught_up"]
    assert not planner.effective_weekly_plan(monday + timedelta(days=1), a.id)["scheduled"]
    assert TranslationPlanner(repo).weekly_schedule(b.id)["target_chapters"] == 10
    assert json.loads(planner.path.read_text(encoding="utf-8"))["extension"] == {"preserved": True}
    planner.save(monday, a.id, "daily", target_chapters=7)
    assert planner.effective_weekly_plan(monday, a.id)["plan"]["target_chapters"] == 7
    planner.save(monday + timedelta(days=1), None, "rest")
    assert planner.effective_weekly_plan(monday + timedelta(days=1), b.id)["source"] == "global_rest"
    planner.save_weekly_schedule(b.id, weekdays=[0], target_chapters=10, caught_up=False)
    assert planner.weekly_schedule(b.id)["target_chapters"] == 10
    assert planner.weekly_schedule(a.id)["target_chapters"] == 20
    planner.save_weekly_schedule(a.id, weekdays=[0], target_chapters=None, caught_up=True)
    assert planner.weekly_schedule(a.id)["target_chapters"] == 20
    planner.save_weekly_schedule(a.id, weekdays=[], target_chapters=20, caught_up=False, enabled=False)
    assert planner.effective_weekly_plan(monday, a.id) is None


@pytest.mark.parametrize("weekdays,target,caught_up", [([7], 1, False), ([True], 1, False),
    ([0], 0, False), ([0], 1.5, False), ([0], None, False)])
def test_weekly_invalid_values_do_not_write(tmp_path, weekdays, target, caught_up):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile()
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    with pytest.raises(ValueError):
        planner.save_weekly_schedule(profile.id, weekdays=weekdays, target_chapters=target, caught_up=caught_up)
    assert not planner.path.exists()


def test_scheduler_ui_and_today_cards(tmp_path):
    from PySide6.QtWidgets import QApplication, QProgressBar, QPushButton
    from novel_workflow.translation_planner_page import TodayPage
    from novel_workflow.today_plan_bar import today_plan_snapshot
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    profiles = [NovelProfile(name=name) for name in ('A', 'B')]
    for p in profiles:
        repo.save_profile(p)
    page = TodayPage(repo)
    page.resize(900, 600)
    page.show()
    page._show_scheduler()
    app.processEvents()
    rows = page.scheduler.rows
    a, b = [rows[p.id] for p in profiles]
    a.target.setValue(20)
    a.enabled.click()
    a.weekdays[date.today().weekday()].click()
    b.caught.click()
    b.weekdays[date.today().weekday()].click()
    app.processEvents()
    assert a.goal_row.isVisible()
    assert not b.goal_row.isVisible()
    assert page.planner.weekly_schedule(profiles[0].id)['target_chapters'] == 20
    assert today_plan_snapshot(page.planner, profiles[1])['status'] == 'caught_up'
    opened = []
    page.openNovel.connect(opened.append)
    page._show_today()
    app.processEvents()
    cards = [page.story_cards_layout.itemAt(i).widget() for i in range(page.story_cards_layout.count())]
    cards = [w for w in cards if w and w.property('profileId')]
    assert {w.property('profileId') for w in cards} == {p.id for p in profiles}
    caught_card = next(w for w in cards if w.property('profileId') == profiles[1].id)
    assert not caught_card.findChildren(QProgressBar)
    for card in cards:
        card.findChild(QPushButton).click()
    assert set(opened) == {p.id for p in profiles}
    page.close()


def test_weekly_toggle_restores_goal_and_scroll_position(tmp_path):
    from PySide6.QtWidgets import QApplication
    from novel_workflow.weekly_scheduler_page import WeeklySchedulerPage
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    profiles = [NovelProfile(name=f'Novel {i}') for i in range(30)]
    for profile in profiles:
        repo.save_profile(profile)
    page = WeeklySchedulerPage(repo)
    page.resize(900, 600)
    page.refresh()
    page.show()
    app.processEvents()
    row = page.rows[profiles[-1].id]
    page.scroll.ensureWidgetVisible(row)
    app.processEvents()
    pos = page.scroll.verticalScrollBar().value()
    assert pos > 0
    row.target.setValue(20)
    row.enabled.click()
    row.caught.click()
    row.caught.click()
    app.processEvents()
    assert row.target.value() == 20
    assert page.scroll.verticalScrollBar().value() == pos
    assert page.planner.weekly_schedule(profiles[-1].id)['target_chapters'] == 20
    page.close()


@pytest.mark.parametrize('width,height', [(900, 600), (1024, 768), (1280, 720), (1920, 1080)])
def test_weekly_controls_fit_viewport(tmp_path, width, height):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication
    from novel_workflow.weekly_scheduler_page import WeeklySchedulerPage
    app = QApplication.instance() or QApplication([])
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name='ตัวอย่างนิยาย')
    repo.save_profile(profile)
    page = WeeklySchedulerPage(repo)
    page.resize(width, height)
    page.refresh()
    page.show()
    app.processEvents()
    row = page.rows[profile.id]
    for button in row.weekdays:
        right = button.mapTo(page.scroll.viewport(), QPoint(button.width(), 0)).x()
        assert right <= page.scroll.viewport().width()
    page.close()


def test_atomic_failure_preserves_original_and_shared_repository_concurrency(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from novel_workflow import storage
    repo = ProjectRepository(tmp_path)
    profiles = [NovelProfile(name=str(i)) for i in range(10)]
    for p in profiles:
        repo.save_profile(p)
    planner = TranslationPlanner(repo)
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lambda p: planner.save_weekly_schedule(
            p.id, weekdays=[0], target_chapters=10, caught_up=False), profiles))
    before = planner.path.read_bytes()
    assert len(json.loads(before)['weekly_schedules']) == len(profiles)
    def fail_replace(*_args):
        raise OSError('simulated disk failure')
    monkeypatch.setattr(storage.os, 'replace', fail_replace)
    with pytest.raises(OSError):
        planner.save_weekly_schedule(profiles[0].id, weekdays=[1], target_chapters=4, caught_up=False)
    assert planner.path.read_bytes() == before


def test_weekly_progress_uses_confirmed_exports(tmp_path):
    from datetime import datetime
    from novel_workflow.today_plan_bar import today_plan_snapshot
    from novel_workflow.translation_progress import record_translator_export
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name='A')
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    day = date.today()
    planner.save_weekly_schedule(profile.id, weekdays=[day.weekday()], target_chapters=5, caught_up=False)
    assert today_plan_snapshot(planner, profile, day)['completed'] == 0
    now = datetime.now().astimezone()
    for event_id in ('a', 'b'):
        record_translator_export(profile, [1, 2], source_path='Translator.txt', digest='a' * 64,
                                 exported_path='export.txt', event_id=event_id, completed_at=now)
    assert today_plan_snapshot(planner, profile, day)['completed'] == 2


def test_story_override_precedes_rest_and_weekly_without_modifying_story(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name='A')
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    day = date.today()
    planner.save_story_schedule(profile.id, 'daily', final_chapter=100,
                                start_day=day, daily_target=5)
    planner.override_story_day(profile.id, day, 3)
    story = planner.story_schedule(profile.id)
    planner.save_weekly_schedule(profile.id, weekdays=[day.weekday()], target_chapters=20, caught_up=False)
    planner.save(day, None, 'rest')
    assert planner.effective_weekly_plan(day, profile.id) == {'source': 'story_override', 'target_chapters': 3}
    assert planner.story_schedule(profile.id) == story
    planner.save(day, profile.id, 'daily', target_chapters=8)
    assert planner.effective_weekly_plan(day, profile.id)['plan']['target_chapters'] == 8


def test_weekly_missed_history_uses_original_goal(tmp_path, monkeypatch):
    import novel_workflow.translation_planner as module
    from datetime import timedelta
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name='A')
    repo.save_profile(profile)
    planner = TranslationPlanner(repo)
    yesterday = date.today() - timedelta(days=1)
    monkeypatch.setattr(module, '_now', lambda: yesterday.isoformat() + 'T09:00:00+00:00')
    planner.save_weekly_schedule(profile.id, weekdays=[yesterday.weekday()], target_chapters=20, caught_up=False)
    monkeypatch.setattr(module, '_now', lambda: date.today().isoformat() + 'T09:00:00+00:00')
    planner.save_weekly_schedule(profile.id, weekdays=[yesterday.weekday()], target_chapters=30, caught_up=False)
    result = planner.weekly_day_result(yesterday, profile)
    assert result['status'] == 'missed'
    assert result['actual'] == 0
    assert result['target_chapters'] == 20
