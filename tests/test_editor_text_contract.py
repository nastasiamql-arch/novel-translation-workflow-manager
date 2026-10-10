import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QMimeData, QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from novel_workflow.text_normalization import remove_empty_lines
from novel_workflow.workspace_editor import EditorTabs
from test_txt_export import app, panel


VOCAB = '康斯坦丁\tคอนสแตนติน\tชาย\tชื่อเรียกคอนสแตนติน ฟอน นอยรัทในวงประชุมผู้นำนาซี'
RAW = '\nไทย 中文\n\n \n\t\n\u00a0\n  English\t \n\n끝'
CLEAN = 'ไทย 中文\n \n\t\n\u00a0\n  English\t \n끝'


@pytest.fixture(autouse=True)
def dispose_test_editors():
    app()
    existing = set(QApplication.topLevelWidgets())
    yield
    # Qt ownership outlives Python locals. Dispose these test editors/timers
    # before subsequent tests repeatedly restyle the entire application.
    for widget in set(QApplication.topLevelWidgets()) - existing:
        for timer in widget.findChildren(QTimer):
            timer.stop()
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.mark.parametrize('sep', ['\n', '\r\n', '\r', '\u2028', '\u2029', '\u0085'])
def test_only_zero_character_lines_are_removed(sep):
    raw = sep + 'ไทย 中文' + sep * 2 + ' ' + sep + '\t' + sep + '\u00a0' + sep + '  B\t ' + sep * 2
    expected = sep.join(['ไทย 中文', ' ', '\t', '\u00a0', '  B\t '])
    assert remove_empty_lines(raw) == expected
    assert remove_empty_lines(expected) == expected


@pytest.mark.parametrize('folder,suffix', [('source', '.txt'), ('translated', '.txt'), ('reviewed', '.txt'), ('polished', '.txt'), ('translated', '.md')])
def test_novel_open_paste_save_copy_reopen_without_open_autosave(tmp_path, folder, suffix):
    app()
    path = tmp_path / folder / ('chapter_1' + suffix)
    path.parent.mkdir()
    path.write_text(RAW, encoding='utf-8')
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    assert editor.toPlainText() == CLEAN
    assert tabs.dirty_count() == 1
    assert not editor.autosave_timer.isActive()
    tabs._autosave_editor(editor)
    assert path.read_text(encoding='utf-8') == RAW
    editor.selectAll()
    mime = QMimeData(); mime.setText(RAW); mime.setHtml('<p>wrong</p>')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == CLEAN
    editor.undo(); assert editor.toPlainText() == CLEAN
    editor.redo(); assert editor.toPlainText() == CLEAN
    editor.selectAll(); editor.copy()
    assert QApplication.clipboard().text() == CLEAN
    assert tabs.save_editor(editor)
    assert path.read_text(encoding='utf-8') == CLEAN
    tabs.apply_external_update(path, path.read_text(encoding='utf-8'))
    assert editor.toPlainText() == CLEAN
    assert EditorTabs().open_file(path).toPlainText() == CLEAN
    editor.autosave_timer.stop()


@pytest.mark.parametrize('relative', ['FDR.txt', 'FDRContext.md', 'FDRGlossary.txt', 'notes/OTHER.MD', 'prompts/Prompt.md', 'style/custom.txt'])
def test_every_open_txt_md_normalizes_regardless_of_name_or_folder(tmp_path, relative):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RAW, encoding='utf-8')
    unopened = tmp_path / 'not-opened.txt'
    unopened.write_text(RAW, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert editor.toPlainText() == CLEAN
    assert path.read_text(encoding='utf-8') == RAW
    assert not editor.autosave_timer.isActive()
    editor.selectAll()
    data = QMimeData(); data.setText(RAW)
    editor.insertFromMimeData(data)
    assert editor.toPlainText() == CLEAN
    editor.selectAll(); editor.copy()
    assert QApplication.clipboard().text() == CLEAN
    assert tabs.save_editor(editor, autosave=True)
    assert path.read_text(encoding='utf-8') == CLEAN
    assert unopened.read_text(encoding='utf-8') == RAW
    assert EditorTabs().open_file(path).toPlainText() == CLEAN


def test_autosave_normalizes_visible_text_preserving_undo_bom_cr(tmp_path):
    app()
    path = tmp_path / 'chapter_1.txt'
    path.write_bytes(b'\xef\xbb\xbfA\rB')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    editor.insertPlainText('\n\nC')
    assert tabs.save_editor(editor, autosave=True)
    assert editor.toPlainText() == 'A\nB\nC'
    assert path.read_bytes() == b'\xef\xbb\xbfA\rB\rC'
    assert editor.document().isUndoAvailable()
    editor.undo(); assert editor.toPlainText() == 'A\nB\n\nC'
    editor.autosave_timer.stop()


@pytest.mark.parametrize('name', ['glossary.txt', 'characters.txt', 'vocabulary.txt', 'data.tsv'])
def test_tsv_exact_plain_html_roundtrip_empty_columns(tmp_path, name):
    app()
    text = VOCAB + '\n\n李秀\tซิ่ว\t\t\n\t\t\t'
    path = tmp_path / name; path.write_text(text, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    expected = remove_empty_lines(text) if name.endswith('.txt') else text
    assert editor.toPlainText() == expected
    mime = QMimeData(); mime.setText(text); mime.setHtml('<table><tr><td>wrong</td></tr></table>')
    editor.selectAll(); editor.insertFromMimeData(mime)
    editor.selectAll(); editor.copy()
    assert QApplication.clipboard().text() == expected
    assert tabs.save_editor(editor, autosave=True)
    assert path.read_text(encoding='utf-8') == expected
    assert EditorTabs().open_file(path).toPlainText() == expected
    assert expected.count('\t') == text.count('\t')
    editor.autosave_timer.stop()


def test_open_context_compacts_all_zero_character_lines(tmp_path):
    app()
    raw = '# Settings\n\nkeep\n\n# Novel Text\n\nA\n\nB\n\n# Glossary\n\n' + VOCAB
    expected = '# Settings\nkeep\n# Novel Text\nA\nB\n# Glossary\n' + VOCAB
    path = tmp_path / 'Context.md'; path.write_text(raw, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert editor.toPlainText() == expected
    assert path.read_text(encoding='utf-8') == raw
    assert tabs.save_editor(editor)
    assert path.read_text(encoding='utf-8') == expected


def test_export_copy_disk_context_agree(tmp_path):
    app()
    context = tmp_path / 'Context.md'; context.write_text('old', encoding='utf-8')
    export = panel(tmp_path, context_path_callback=lambda: context)
    export.editor.setPlainText(RAW)
    export.copy_text()
    assert QApplication.clipboard().text() == CLEAN
    assert export.editor.toPlainText() == CLEAN
    assert export.export(update_context=True)
    assert context.read_text(encoding='utf-8') == 'old'
    assert (tmp_path / 'segverified1.txt').read_text(encoding='utf-8') == CLEAN


def test_paste_leading_separator_never_joins_neighboring_lines(tmp_path):
    app()
    export = panel(tmp_path); export.editor.setPlainText('previous')
    export.editor.moveCursor(export.editor.textCursor().MoveOperation.End)
    data = QMimeData(); data.setText('\n\nnext\n\nlast')
    export.editor.insertFromMimeData(data)
    assert export.editor.toPlainText() == 'previous\nnext\nlast'
    export.editor.undo(); assert export.editor.toPlainText() == 'previous'


def test_open_context_compacts_fence_and_paste_without_changing_characters(tmp_path):
    app()
    raw = '# Novel Text\n\nA\n\n```json\n{\n\n}\n```\n\nB\n\n# Settings\n\nold'
    expected = '# Novel Text\nA\n```json\n{\n}\n```\nB\n# Settings\nold'
    path = tmp_path / 'Context.md'; path.write_text(raw, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert editor.toPlainText() == expected
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    data = QMimeData(); data.setText('\n\nnew\n\nvalue')
    editor.insertFromMimeData(data)
    assert editor.toPlainText() == expected + '\nnew\nvalue'
    editor.autosave_timer.stop()


def test_card_selection_preserves_font_weight_and_size():
    app()
    from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyleOptionViewItem, QStyle
    from novel_workflow.profile_list import ProfileItemDelegate
    view = QListWidget(); view.addItem(QListWidgetItem('ไทย 中文'))
    delegate = ProfileItemDelegate(view)
    regular = QStyleOptionViewItem(); selected = QStyleOptionViewItem()
    selected.state |= QStyle.State_Selected
    delegate.initStyleOption(regular, view.model().index(0, 0))
    delegate.initStyleOption(selected, view.model().index(0, 0))
    assert selected.font == regular.font


def test_open_context_copy_partial_fence_compacts_blank_lines(tmp_path):
    app()
    raw = '# Novel Text\nA\n```json\n{\n\n}\n```\nB\n# Settings\n\nvalue'
    path = tmp_path / 'Context.md'; path.write_text(raw, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    cursor = editor.textCursor()
    visible = editor.toPlainText()
    start = visible.index('{'); end = visible.index('}') + 1
    cursor.setPosition(start); cursor.setPosition(end, cursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor); editor.copy()
    assert QApplication.clipboard().text() == '{\n}'


def test_normalization_conflict_and_failed_save_keep_recovery(tmp_path, monkeypatch):
    app()
    import json
    import novel_workflow.workspace_editor as module
    path = tmp_path / 'chapter_1.txt'; path.write_text('A', encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    editor.setPlainText(RAW); path.write_text('external', encoding='utf-8')
    assert not tabs.save_editor(editor, quiet=True, autosave=True)
    assert path.read_text(encoding='utf-8') == 'external'
    assert editor.toPlainText() == CLEAN
    recovery = json.loads(tabs._recovery_path(path).read_text(encoding='utf-8'))
    assert recovery['text'] == CLEAN
    assert tabs.dirty_count() == 1
    tabs.apply_external_update(path, 'external')
    editor.setPlainText(recovery['text'])
    def fail(*_args):
        raise PermissionError('locked')
    monkeypatch.setattr(module.os, 'replace', fail)
    assert not tabs.save_editor(editor, quiet=True)
    assert editor.toPlainText() == CLEAN
    assert path.read_text(encoding='utf-8') == 'external'
    assert tabs._recovery_path(path).is_file()
    editor.autosave_timer.stop()


def test_tsv_incomplete_rows_warn_without_repair(tmp_path):
    app()
    path = tmp_path / 'glossary.txt'; path.write_text('CN\tTH', encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert 'TSV' in tabs.status.text()
    assert editor.toPlainText() == 'CN\tTH'
    assert tabs.save_editor(editor)
    assert path.read_text(encoding='utf-8') == 'CN\tTH'


def test_legacy_file_editor_uses_novel_contract(tmp_path):
    app()
    from novel_workflow.ui import Editor
    path = tmp_path / 'source' / 'chapter_1.txt'
    dialog = Editor(None, 'Edit', RAW, path=path)
    assert dialog.text() == CLEAN


def test_open_only_close_preserves_disk(tmp_path):
    app()
    path = tmp_path / 'chapter_1.txt'; path.write_text(RAW, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert tabs.save_all(include_normalization=False)
    assert path.read_text(encoding='utf-8') == RAW
    tabs.close_tab(tabs.tabs.indexOf(editor))
    assert path.read_text(encoding='utf-8') == RAW


def test_legacy_recovery_is_normalized_on_restore(tmp_path, monkeypatch):
    app()
    import json
    path = tmp_path / 'chapter_1.txt'; path.write_text('disk', encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    recovery = tabs._recovery_path(path); recovery.parent.mkdir(parents=True)
    recovery.write_text(json.dumps({'path': str(path.resolve()), 'text': RAW}), encoding='utf-8')
    tabs.restore_recovery(editor)
    assert editor.toPlainText() == CLEAN
    assert path.read_text(encoding='utf-8') == 'disk'
