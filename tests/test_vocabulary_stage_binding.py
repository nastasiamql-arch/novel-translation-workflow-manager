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



def test_select_folder_of_numbered_txt_uses_existing_vocabulary_step_files(tmp_path, monkeypatch):
    """0601.txt..0629.txt can be batched without linking a chapter one by one."""
    import zipfile
    from PySide6.QtWidgets import QFileDialog
    from novel_workflow.models import AppSettings

    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    _, prompt = _add(profile, root, "prompts/Find Words.md", "หาศัพท์")
    _, glossary = _add(profile, root, "glossary/术语.md", "人物：小明")
    _, combined = _add(profile, root, "old/FATE.txt", "第一章 头\n正文\n第二章 头\n内容")
    _, disabled = _add(profile, root, "private/disabled.txt", "not selected", enabled=False)
    folder = tmp_path / "chapter_source"
    folder.mkdir()
    for n in range(601, 630):
        (folder / f"{n:04d}.txt").write_text(f"第{n}章\n中文 ไทย", encoding="utf-8")
    saved = []
    page = TxtVocabularyPage(
        {}, lambda state: saved.append(dict(state)), root / "source",
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile),
        archive_cache_dir=tmp_path / "archives",
    )
    page.show()
    app.processEvents()
    chooser = page.findChild(QPushButton, "txtVocabularyChooseFolder")
    assert chooser is not None and chooser.isVisible()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(folder))
    chooser.click()
    assert saved[-1]["source_mode"] == "folder"
    assert Path(saved[-1]["source_folder"]) == folder
    assert page.source_picker.currentData() is None
    assert "chapter_source" in page.folder_label.text()
    assert len(page._groups) == 6
    assert [(b.start, b.end, len(b.chapters)) for b in page._groups] == [
        (601, 605, 5), (606, 610, 5), (611, 615, 5),
        (616, 620, 5), (621, 625, 5), (626, 629, 4)
    ]
    copy1 = page.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert copy1 is not None and "7 ไฟล์" in copy1.text()
    copy1.click()
    contents = {Path(url.toLocalFile()) for url in app.clipboard().mimeData().urls()}
    assert prompt in contents and glossary in contents
    assert combined not in contents and disabled not in contents
    assert len(contents) == 7
    assert sorted(p.name for p in contents if p.parent == folder) == [
        f"{n:04d}.txt" for n in range(601, 606)
    ]

    page.zip_toggle.setChecked(True)
    copy6 = page.findChild(QPushButton, "txtVocabularyCopyBatch6")
    assert copy6 is not None
    copy6.click()
    archives = [Path(url.toLocalFile()) for url in app.clipboard().mimeData().urls()]
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as packed:
        assert packed.testzip() is None
        assert len(packed.namelist()) == 6
        assert "chapters/0629.txt" in packed.namelist()
        assert "vocabulary/术语.md" in packed.namelist()
        assert packed.read("chapters/0629.txt") == (folder / "0629.txt").read_bytes()
    assert len(list(folder.iterdir())) == 29  # No source renaming or writing.
    settings = AppSettings()
    settings.vocabulary_txt_profiles[profile.id] = saved[-1]
    repo.save_settings(settings)
    assert repo.load_settings().vocabulary_txt_profiles[profile.id]["source_folder"] == str(folder)

    reopened = TxtVocabularyPage(
        repo.load_settings().vocabulary_txt_profiles[profile.id], lambda _: None, root / "source",
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile),
    )
    assert reopened._using_folder()
    assert reopened._groups[0].start == 601
    assert reopened.zip_toggle.isChecked()
    reopened.close()
    page.close()


def test_folder_chooser_cancel_empty_or_duplicate_does_not_change_selection(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    _add(profile, root, "prompts/find.md", "Find Terms")
    valid = tmp_path / "valid"
    valid.mkdir()
    (valid / "0601.txt").write_text("内容", encoding="utf-8")
    invalid = tmp_path / "empty"
    invalid.mkdir()
    duplicate = tmp_path / "duplicate"
    duplicate.mkdir()
    (duplicate / "0601.txt").write_text("1", encoding="utf-8")
    (duplicate / "0601 another.txt").write_text("1", encoding="utf-8")
    selected = [str(valid), "", str(invalid), str(duplicate)]
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: selected.pop(0))
    alerts = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: alerts.append(args[2]))
    changes = []
    page = TxtVocabularyPage({}, lambda value: changes.append(value),
                             root / "source", stage_reader=lambda: enabled_vocabulary_attachments(
                                 repo, AssemblyService(repo), profile))
    chooser = page.findChild(QPushButton, "txtVocabularyChooseFolder")
    chooser.click()
    assert len(page._groups) == 1
    snapshot = dict(page.state)
    chooser.click()  # Cancel: no changes
    chooser.click()  # Empty: warning, no changes
    chooser.click()  # Duplicate chapter: warning, no changes
    assert page.state == snapshot
    assert len(changes) == 1
    assert len(alerts) == 2
    assert page._groups[0].start == 601
    page.close()


def test_folder_without_stage_source_and_switch_back_to_stage(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    app = QApplication.instance() or QApplication([])
    repo, profile, root = _profile(tmp_path)
    selected_source, linked = _add(
        profile, root, "old/FATE.txt",
        "第一章 标题\n正文\n第二章 标题\n内容"
    )
    direct = tmp_path / "numbered"
    direct.mkdir()
    for n in range(601, 606):
        (direct / f"{n:04d}.txt").write_text(str(n), encoding="utf-8")
    page = TxtVocabularyPage(
        {}, lambda _: None, root / "old",
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), profile),
    )
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: str(direct))
    page.choose_folder()
    assert len(page._groups) == 1
    assert page.source_picker.currentData() is None
    page.source_picker.setCurrentIndex(page.source_picker.findData(selected_source.id))
    assert not page._using_folder()
    assert page.source_picker.currentData() == selected_source.id
    page.tabs.setCurrentIndex(1)
    app.processEvents()
    assert page.preview_table.rowCount() == 2
    page.close()

    # Another novel with zero stage files may still use its chosen chapter folder;
    # there is no dependency on a linked file for the chapter source itself.
    other = NovelProfile()
    standalone = TxtVocabularyPage(
        {"source_mode": "folder", "source_folder": str(direct)},
        lambda _: None, direct,
        stage_reader=lambda: enabled_vocabulary_attachments(repo, AssemblyService(repo), other),
    )
    copy = standalone.findChild(QPushButton, "txtVocabularyCopyBatch1")
    assert copy is not None and copy.isEnabled()
    copy.click()
    assert len(app.clipboard().mimeData().urls()) == 5
    standalone.close()
