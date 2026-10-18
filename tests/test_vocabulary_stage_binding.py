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
