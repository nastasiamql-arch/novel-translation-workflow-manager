"""TXT vocabulary integration uses only the existing enabled vocabulary-stage files."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from novel_workflow.models import NovelProfile, StepFile
from novel_workflow.services import AssemblyService
from novel_workflow.storage import ProjectRepository
from novel_workflow.vocabulary_batch_page import TxtVocabularyPage
from novel_workflow.vocabulary_source_binding import (
    batch_stage_files, enabled_vocabulary_attachments, suggest_source_id,
)
from novel_workflow.vocabulary_batches import make_chapter_batches, scan_chapter_files


def _profile(tmp_path):
    repo = ProjectRepository(tmp_path / "storage")
    profile = NovelProfile()
    root = repo.profile_dir(profile.id)
    root.mkdir(parents=True)
    return repo, profile, root


def _add(profile, root, relative, text, *, enabled=True, ref="repository_file"):
    file = root / relative
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(text, encoding="utf-8")
    entry = StepFile(label=file.stem, path=relative, reference_type=ref, enabled=enabled,
                     order=len(profile.vocabulary_step.files))
    profile.vocabulary_step.files.append(entry)
    return entry, file


def test_enabled_step_only_and_real_files_batch_copy(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    prompt, prompt_file = _add(profile, root, "prompts/find_words.md", "คำสั่ง")
    words, words_file = _add(profile, root, "glossary/words.txt", "人物：你好")
    hidden, hidden_file = _add(profile, root, "glossary/disabled.txt", "Do not copy", enabled=False)
    source, source_file = _add(profile, root, "source/0111 第一章.txt", "第111章 中文")
    for n in range(112, 116):
        _add_file = root / "source" / f"{n:04d} 中文章节.txt"
        _add_file.write_text(f"第{n}章", encoding="utf-8")
    other = root / "translated" / "do_not_copy.txt"
    other.parent.mkdir()
    other.write_text("Not vocabulary", encoding="utf-8")
    entries = enabled_vocabulary_attachments(repo, AssemblyService(repo), profile)
    assert {e.id for e in entries} == {prompt.id, words.id, source.id}
    assert suggest_source_id(entries) == source.id
    page = TxtVocabularyPage(
        {"batch_size": 5}, lambda state: None, root / "source",
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile),
    )
    assert page.source_picker.currentData() == source.id
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert button is not None and "7 ไฟล์" in button.text()
    app.clipboard().setText("sentinel")
    button.click()
    paths = {Path(url.toLocalFile()) for url in app.clipboard().mimeData().urls()}
    assert len(paths) == 7
    assert prompt_file in paths and words_file in paths
    assert hidden_file not in paths and other not in paths
    assert len([p for p in paths if p.parent == root / "source"]) == 5
    page.close()


def test_missing_active_vocabulary_file_keeps_clipboard(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    source, file = _add(profile, root, "source/0001.txt", "第一章")
    missing = StepFile(path="prompts/not-found.md", label="หาศัพท์ prompt",
                       order=2, enabled=True)
    profile.vocabulary_step.files.append(missing)
    page = TxtVocabularyPage({}, lambda state: None, root / "source",
                             stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile))
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert button is not None and not button.isEnabled()
    app.clipboard().setText("keep me")
    assert app.clipboard().text() == "keep me"
    missing.enabled = False
    page.refresh()
    replacement = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert replacement is not None and replacement.isEnabled()
    replacement.click()
    assert len(app.clipboard().mimeData().urls()) == 1
    page.close()


def test_linked_combined_source_auto_loads_and_splits_without_paste(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    source, file = _add(profile, root, "source/FATE.txt",
                        "".join(f"第{n}章 标题{n}\n内容{n}\n\n" for n in range(1, 101)))
    _add(profile, root, "prompts/Find Terms.md", "Find vocabulary")
    page = TxtVocabularyPage({}, lambda state: None, root / "source",
                             stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile))
    assert page.source_picker.currentData() == source.id
    page.tabs.setCurrentIndex(1)
    app.processEvents()
    assert page.preview_table.rowCount() == 100
    assert "第1章" in page.pasted_text.toPlainText()
    output = root / "source"
    assert not (output / "0001 标题1.txt").exists()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.Ok)
    page.save_button.click()
    assert (output / "0001 标题1.txt").exists()
    assert (output / "0100 标题100.txt").exists()
    assert len(page._groups) == 20
    copy = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    copy.click()
    copied = {Path(url.toLocalFile()).name for url in app.clipboard().mimeData().urls()}
    assert len(copied) == 6
    assert "Find Terms.md" in copied
    assert "FATE.txt" not in copied
    page.close()


def test_source_selector_no_cross_stage_or_ambiguous_auto_selection(tmp_path):
    repo, profile, root = _profile(tmp_path)
    one, file1 = _add(profile, root, "source/0001.txt", "第一章")
    two, file2 = _add(profile, root, "source/0002.txt", "第二章")
    assert suggest_source_id(enabled_vocabulary_attachments(repo, AssemblyService(repo), profile)) is None
    profile.vocabulary_step.files[0].enabled = False
    entries = enabled_vocabulary_attachments(repo, AssemblyService(repo), profile)
    assert suggest_source_id(entries) == two.id
    from novel_workflow.models import WorkflowStep
    profile.workflow.steps = [WorkflowStep(name="แปล",
        files=[StepFile(path="source/0001.txt", enabled=True)])]
    assert len(enabled_vocabulary_attachments(repo, AssemblyService(repo), profile)) == 1


def test_compact_rows_and_zip_toggle_persist_per_novel(tmp_path):
    import zipfile
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    _, prompt = _add(profile, root, "prompts/查找术语.md", "指令")
    _, glossary = _add(profile, root, "glossary/术语表.txt", "术语\n中文")
    _add(profile, root, "source/0001 开始.txt", "第1章")
    for n in range(2, 6):
        (root / "source" / f"{n:04d} 中文.txt").write_text(f"第{n}章", encoding="utf-8")
    saved = []
    cache = tmp_path / "cache"
    page = TxtVocabularyPage(
        {}, lambda value: saved.append(value), root / "source",
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile),
        archive_cache_dir=cache,
    )
    page.resize(1050, 650)
    page.show()
    app.processEvents()
    card = page.findChild(__import__("PySide6.QtWidgets", fromlist=["QFrame"]).QFrame, "txtVocabularyRow")
    assert card is not None
    assert card.height() < 90, card.height()
    button = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert "7 ไฟล์" in button.text()
    page.zip_toggle.setChecked(True)
    assert saved[-1]["copy_as_zip"] is True
    assert "ZIP" in button.text()
    page.scroll.verticalScrollBar().setValue(0)
    button.click()
    data = app.clipboard().mimeData()
    paths = [Path(url.toLocalFile()) for url in data.urls()]
    assert len(paths) == 1 and paths[0].is_file()
    assert paths[0].parent == cache
    with zipfile.ZipFile(paths[0]) as archive:
        assert archive.testzip() is None
        names = archive.namelist()
        assert len(names) == 7
        assert sum(name.startswith("chapters/") for name in names) == 5
        assert "vocabulary/查找术语.md" in names
        assert "vocabulary/术语表.txt" in names
        assert archive.read("vocabulary/术语表.txt") == glossary.read_bytes()
    page.zip_toggle.setChecked(False)
    assert saved[-1]["copy_as_zip"] is False
    button.click()
    assert len(app.clipboard().mimeData().urls()) == 7
    assert paths[0].exists()  # ZIP remains available even after switching mode.
    page.close()


def test_zip_naming_collisions_and_failure_leave_clipboard_untouched(tmp_path, monkeypatch):
    import zipfile
    from novel_workflow.vocabulary_zip import create_txt_batch_zip
    app = QApplication.instance() or QApplication([])
    chapters = tmp_path / "source"
    chapters.mkdir()
    reference1 = tmp_path / "ref1"
    reference2 = tmp_path / "ref2"
    reference1.mkdir()
    reference2.mkdir()
    source = chapters / "0001 中国.txt"
    a = reference1 / "words.txt"
    b = reference2 / "words.txt"
    for path, content in [(source, "正文"), (a, "第一"), (b, "第二")]:
        path.write_text(content, encoding="utf-8")
    archive = create_txt_batch_zip([source, a, b], 1, 1, 1, tmp_path / "cache")
    with zipfile.ZipFile(archive) as zip_in:
        assert set(zip_in.namelist()) == {
            "chapters/0001 中国.txt", "vocabulary/words.txt",
            "vocabulary/words (2).txt",
        }
        assert zip_in.read("vocabulary/words.txt") == a.read_bytes()
        assert zip_in.read("vocabulary/words (2).txt") == b.read_bytes()
    before = set((tmp_path / "cache").iterdir())
    with __import__("pytest").raises(FileNotFoundError):
        create_txt_batch_zip([source, tmp_path / "missing.txt"], 1, 1, 1, tmp_path / "cache")
    assert set((tmp_path / "cache").iterdir()) == before
    app.clipboard().setText("keep original clipboard")
    with __import__("pytest").raises(ValueError):
        create_txt_batch_zip([source], 0, 1, 1, tmp_path / "cache")
    assert app.clipboard().text() == "keep original clipboard"


def test_zip_preference_isolated_from_global_workflow_settings(tmp_path):
    from novel_workflow.models import AppSettings
    from novel_workflow.storage import ProjectRepository
    repo = ProjectRepository(tmp_path / "data")
    settings = AppSettings()
    settings.copy_files_as_zip = False
    settings.vocabulary_txt_profiles["one"] = {"copy_as_zip": True}
    settings.vocabulary_txt_profiles["two"] = {"copy_as_zip": False}
    repo.save_settings(settings)
    saved = repo.load_settings()
    assert saved.vocabulary_txt_profiles["one"]["copy_as_zip"] is True
    assert saved.vocabulary_txt_profiles["two"]["copy_as_zip"] is False
    assert saved.copy_files_as_zip is False
