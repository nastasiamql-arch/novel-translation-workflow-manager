"""Opt-in chapter-review workflow handoff: defaults and safety guards."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dataclasses import asdict

from novel_workflow.auto_chapter_review import review_step_index, suggested_review_step_ids
from novel_workflow.models import NovelProfile, StepFile, Workflow, WorkflowStep
from novel_workflow.storage import ProjectRepository


def read_profile(repo, pid):
    return next(item for item in repo.list_profiles() if item.id == pid)


def test_review_handoff_is_disabled_by_default_and_round_trips(tmp_path):
    repo = ProjectRepository(tmp_path)
    profile = NovelProfile(name="Novel A")
    repo.save_profile(profile)
    loaded = read_profile(repo, profile.id)
    assert loaded.auto_review_enabled is False
    assert review_step_index(loaded, 0, "FATETranslator.txt") is None
    reloaded = NovelProfile.from_dict(asdict(loaded))
    assert reloaded.auto_review_enabled is False
    assert reloaded.auto_review_step_id is None


def test_explicit_custom_review_stage_and_guards():
    profile = NovelProfile(workflow=Workflow([
        WorkflowStep(name="ขั้นตอนแปลของฉัน"),
        WorkflowStep(name="ตรวจสอบบท"),
        WorkflowStep(name="ส่งงาน"),
    ]))
    source, review, _ = profile.workflow.steps
    assert suggested_review_step_ids(profile) == (None, review.id)
    profile.auto_review_enabled = True
    profile.auto_review_translation_step_id = source.id
    profile.auto_review_step_id = review.id
    assert review_step_index(profile, 0, "FATETranslator.txt") == 1
    assert review_step_index(profile, 1, "FATETranslator.txt") is None
    assert review_step_index(profile, 0, "FATE.txt") is None
    assert review_step_index(profile, 0, "Translator.txt") is None
    assert review_step_index(profile, 0, "FATEContext.txt") is None
    profile.auto_review_step_id = source.id
    assert review_step_index(profile, 0, "FATETranslator.txt") is None
    profile.auto_review_step_id = "missing-step-id"
    assert review_step_index(profile, 0, "FATETranslator.txt") is None


def test_preferred_names_and_per_novel_persistence(tmp_path):
    repo = ProjectRepository(tmp_path)
    first = NovelProfile(name="First")
    second = NovelProfile(name="Second")
    assert suggested_review_step_ids(first) == tuple(step.id for step in first.workflow.steps)
    first.auto_review_enabled = True
    first.auto_review_translation_step_id = first.workflow.steps[0].id
    first.auto_review_step_id = first.workflow.steps[1].id
    repo.save_profile(first)
    repo.save_profile(second)
    one = read_profile(repo, first.id)
    two = read_profile(repo, second.id)
    assert one.auto_review_enabled is True
    assert one.auto_review_step_id == first.auto_review_step_id
    assert two.auto_review_enabled is False
    assert review_step_index(one, 0, "FATETranslator.txt") == 1
    assert review_step_index(two, 0, "FATETranslator.txt") is None


def test_settings_switch_is_disabled_and_isolated_per_novel(tmp_path):
    from PySide6.QtWidgets import QApplication
    from novel_workflow.workspace_window import MainWindow
    from test_release_36 import setup_profile

    app = QApplication.instance() or QApplication([])
    repo, first, _ = setup_profile(tmp_path)
    second = NovelProfile(name="Other")
    repo.save_profile(second)
    window = MainWindow(repo)
    window.settings_dialog()
    assert not window.settings_auto_review_enabled.isChecked()
    assert window.settings_auto_review_source.currentData() == first.workflow.steps[0].id
    assert window.settings_auto_review_target.currentData() == first.workflow.steps[1].id
    window.settings_auto_review_enabled.setChecked(True)
    assert read_profile(repo, first.id).auto_review_enabled
    next_index = next(i for i, p in enumerate(window.ps_list) if p.id == second.id)
    window.select_profile(next_index)
    assert window.profile.id == second.id
    assert not window.settings_auto_review_enabled.isChecked()
    assert not read_profile(repo, second.id).auto_review_enabled
    window.close()


def test_saved_translator_handoff_once_with_no_export_or_modification(tmp_path, monkeypatch):
    import hashlib
    from PySide6.QtWidgets import QApplication
    from novel_workflow.workspace_window import MainWindow
    from test_release_36 import setup_profile

    app = QApplication.instance() or QApplication([])
    repo, profile, _ = setup_profile(tmp_path)
    folder = repo.profile_dir(profile.id) / "source"
    folder.mkdir(exist_ok=True)
    translator = folder / "FATETranslator.txt"
    translator.write_text("บทที่ 3\nแปลเรียบร้อย", encoding="utf-8")
    context = folder / "FATEContext.txt"
    context.write_text("บทที่ 2", encoding="utf-8")
    profile.context_path = str(context)
    profile.working_files = [StepFile(path="source/FATETranslator.txt")]
    profile.auto_review_enabled = True
    profile.auto_review_translation_step_id = profile.workflow.steps[0].id
    profile.auto_review_step_id = profile.workflow.steps[1].id
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(translator)
    workspace.editor.tabs.setCurrentWidget(editor)
    workspace.step_index = 0
    copied = []
    monkeypatch.setattr(window, "copy_named_stage", lambda pid, index: copied.append((pid, index)))
    before = hashlib.sha256(translator.read_bytes()).hexdigest()
    window._schedule_auto_chapter_review(str(translator))
    assert workspace.auto_chapter_review_timer.isActive()
    workspace.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    window._run_auto_chapter_review(profile.id)
    assert copied == [(profile.id, 1)]
    assert hashlib.sha256(translator.read_bytes()).hexdigest() == before
    assert context.read_text(encoding="utf-8") == "บทที่ 2"
    window._close_export_reminder_accepted = True
    window.close()


def test_original_source_detection_rejects_context_and_unbound_files(tmp_path):
    from novel_workflow.auto_chapter_review import is_original_source_document, scan_original_chapter_issues
    source = tmp_path / "source"
    source.mkdir()
    main_folder = tmp_path / "external"
    main_folder.mkdir()
    file = source / "FATE.txt"
    assert is_original_source_document(file, set(), source)
    assert is_original_source_document(main_folder / "FATE.txt", set(), source, str(main_folder))
    assert not is_original_source_document(tmp_path / "random.txt", set(), source)
    assert not is_original_source_document(source / "FATETranslator.txt", {source / "FATETranslator.txt"}, source)
    assert not is_original_source_document(source / "FATEContext.txt", {source / "FATEContext.txt"}, source)
    assert not is_original_source_document(source / "FATEGlossary.txt", {source / "FATEGlossary.txt"}, source)
    assert not is_original_source_document(source / "FATE.json", set(), source)
    heads, issues = scan_original_chapter_issues("第1章 开始\n正文\n第1章 又一章\n第3章 结尾\n")
    assert [h.number for h in heads] == [1, 1, 3]
    assert issues == ["ปกติ", "เลขซ้ำ", "เลขกระโดด / อาจมีบทขาดจริง"]


def test_auto_source_review_opens_existing_inspector_only_when_issues(tmp_path, monkeypatch):
    import hashlib
    from PySide6.QtWidgets import QApplication
    from novel_workflow.workspace_window import MainWindow
    from test_release_36 import setup_profile

    app = QApplication.instance() or QApplication([])
    repo, profile, _ = setup_profile(tmp_path)
    source = repo.profile_dir(profile.id) / "source" / "FATE.txt"
    source.parent.mkdir(exist_ok=True)
    source.write_text("第1章 开始\n正文\n第1章 又一章", encoding="utf-8")
    (source.parent / "FATETranslator.txt").write_text("บทที่ 0\nยังไม่เริ่ม", encoding="utf-8")
    profile.auto_review_enabled = True
    repo.save_profile(profile)
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    workspace = window.workspaces[profile.id]
    editor = workspace.editor.open_file(source)
    workspace.editor.tabs.setCurrentWidget(editor)
    inspections, messages = [], []
    monkeypatch.setattr(workspace, "inspect_chapter_numbers", lambda: inspections.append("review"))
    monkeypatch.setattr(window, "show_submit_toast", messages.append)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    window._schedule_auto_chapter_review(str(source))
    assert workspace.auto_chapter_review_timer.isActive()
    assert workspace.auto_chapter_review_timer.interval() == 2500
    workspace.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    window._run_auto_chapter_review(profile.id)
    assert inspections == ["review"]
    assert any("พบปัญหาเลขบท" in msg for msg in messages)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before

    source.write_text("第1章 开始\n正文\n第2章 又一章", encoding="utf-8")
    editor.disk_digest = hashlib.sha256(source.read_bytes()).digest()
    editor.setPlainText(source.read_text(encoding="utf-8"))
    editor.setProperty("documentSavedText", editor.toPlainText())
    workspace.editor._set_dirty(editor, False)
    window._schedule_auto_chapter_review(str(source))
    workspace.auto_chapter_review_timer.stop()
    window._run_auto_chapter_review(profile.id)
    assert inspections == ["review"]
    assert any("ลำดับปกติ" in msg for msg in messages)
    window._close_export_reminder_accepted = True
    window.close()


def test_source_auto_review_disabled_does_not_schedule(tmp_path):
    from PySide6.QtWidgets import QApplication
    from novel_workflow.workspace_window import MainWindow
    from test_release_36 import setup_profile
    app = QApplication.instance() or QApplication([])
    repo, profile, _ = setup_profile(tmp_path)
    source = repo.profile_dir(profile.id) / "source" / "FATE.txt"
    source.parent.mkdir(exist_ok=True)
    source.write_text("第1章 正文", encoding="utf-8")
    window = MainWindow(repo)
    window.select_profile(next(i for i, p in enumerate(window.ps_list) if p.id == profile.id))
    workspace = window.workspaces[profile.id]
    window._schedule_auto_chapter_review(str(source))
    assert not hasattr(workspace, "auto_chapter_review_timer")
    window._close_export_reminder_accepted = True
    window.close()
