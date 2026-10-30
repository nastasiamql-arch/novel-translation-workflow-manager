import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QMimeData, QTimer, QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from novel_workflow.text_normalization import remove_empty_lines
from novel_workflow.workspace_editor import CodeEditor, EditorTabs
from test_txt_export import app, panel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest


VOCAB = '康斯坦丁\tคอนสแตนติน\tชาย\tชื่อเรียกคอนสแตนติน ฟอน นอยรัทในวงประชุมผู้นำนาซี'
RAW = '\nไทย 中文\n\n \n\t\n\u00a0\n  English\t \n\n끝'
CLEAN = 'ไทย 中文\n \n\t\n\u00a0\n  English\t \n끝'


def test_find_replace_stays_visible_and_undoes_unicode_replacement(tmp_path):
    app()
    first = tmp_path / 'first.txt'; first.write_text('ไทย 中文 abc 中文', encoding='utf-8')
    second = tmp_path / 'second.md'; second.write_text('中文 other', encoding='utf-8')
    tabs = EditorTabs(); tabs.resize(500, 450); tabs.show(); tabs.activateWindow()
    editor = tabs.open_file(first); other = tabs.open_file(second)
    tabs.tabs.setCurrentWidget(editor); editor.setFocus(); QTest.qWait(30)
    QTest.keyClick(editor, Qt.Key_F, Qt.ControlModifier)
    assert tabs.find_panel.isVisible() and tabs.replace_row.isVisible()
    assert tabs.find_input.hasFocus()
    tabs.find_input.setText('中文')
    assert tabs.find_count.text() == '1/2'
    QTest.keyClick(tabs.find_input, Qt.Key_Return)
    assert tabs.find_count.text() == '2/2'
    QTest.keyClick(tabs.find_input, Qt.Key_Return, Qt.ShiftModifier)
    assert tabs.find_count.text() == '1/2'
    editor.setFocus(); QApplication.processEvents()
    assert tabs.find_panel.isVisible()
    tabs.tabs.setCurrentWidget(other); QApplication.processEvents()
    assert tabs.find_panel.isVisible() and tabs.find_count.text().endswith('/1')
    tabs.tabs.setCurrentWidget(editor); tabs.resize(360, 400); QApplication.processEvents()
    assert tabs.find_panel.isVisible() and tabs.rect().contains(tabs.find_panel.geometry())
    QTest.keyClick(editor, Qt.Key_H, Qt.ControlModifier)
    assert tabs.replace_input.hasFocus()
    tabs.replace_input.setText('替换更长')
    tabs._find_next()
    tabs.replace_current_button.click()
    assert editor.toPlainText().count('替换更长') == 1
    editor.undo()
    assert editor.toPlainText() == 'ไทย 中文 abc 中文'
    tabs.replace_all_button.click()
    assert editor.toPlainText() == 'ไทย 替换更长 abc 替换更长'
    assert other.toPlainText() == '中文 other'
    editor.undo()
    assert editor.toPlainText() == 'ไทย 中文 abc 中文'
    tabs.find_input.setFocus(); QTest.keyClick(tabs.find_input, Qt.Key_Escape)
    assert not tabs.find_panel.isVisible()


def test_find_large_document_refreshes_after_text_changes(tmp_path):
    app()
    path = tmp_path / 'large.md'
    path.write_text(('ไทย abc 中文\n' * 5000) + 'end', encoding='utf-8')
    tabs = EditorTabs(); tabs.show()
    editor = tabs.open_file(path)
    tabs.show_find(); tabs.find_input.setText('中文')
    assert tabs.find_count.text().endswith('/5000')
    tabs.find_input.setText('ไม่พบ')
    assert tabs.find_count.text() == '0/0'
    tabs.find_input.setText('end')
    assert tabs.find_count.text().endswith('/1')
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    editor.insertPlainText('end')
    QTest.qWait(250)
    assert tabs.find_count.text().endswith('/2')


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
    assert editor.toPlainText() == CLEAN + '\n'
    editor.undo(); assert editor.toPlainText() == CLEAN
    editor.redo(); assert editor.toPlainText() == CLEAN + '\n'
    editor.selectAll(); editor.copy()
    assert QApplication.clipboard().text() == CLEAN
    assert tabs.save_editor(editor)
    assert path.read_text(encoding='utf-8') == CLEAN
    assert editor.toPlainText() == CLEAN + '\n'
    tabs.apply_external_update(path, path.read_text(encoding='utf-8'))
    assert editor.toPlainText() == CLEAN
    assert EditorTabs().open_file(path).toPlainText() == CLEAN
    editor.autosave_timer.stop()


@pytest.mark.parametrize('relative,compact', [
    ('FDR.txt', True), ('FDRContext.md', True), ('FDRGlossary.txt', False),
    ('notes/OTHER.MD', True), ('prompts/Prompt.md', False), ('style/custom.txt', False),
])
def test_open_text_compacts_prose_but_preserves_structured_documents(tmp_path, relative, compact):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(RAW, encoding='utf-8')
    unopened = tmp_path / 'not-opened.txt'
    unopened.write_text(RAW, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    visible = CLEAN if compact else RAW
    assert editor.toPlainText() == visible
    assert path.read_text(encoding='utf-8') == RAW
    assert not editor.autosave_timer.isActive()
    editor.selectAll()
    data = QMimeData(); data.setText(RAW)
    editor.insertFromMimeData(data)
    assert editor.toPlainText() == visible + '\n'
    editor.selectAll(); editor.copy()
    assert QApplication.clipboard().text() == visible
    assert tabs.save_editor(editor, autosave=True)
    assert path.read_text(encoding='utf-8') == visible
    assert unopened.read_text(encoding='utf-8') == RAW
    assert EditorTabs().open_file(path).toPlainText() == visible


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
    expected = text
    assert editor.toPlainText() == expected
    mime = QMimeData(); mime.setText(text); mime.setHtml('<table><tr><td>wrong</td></tr></table>')
    editor.selectAll(); editor.insertFromMimeData(mime)
    editor.selectAll(); editor.copy()
    expected_after_paste = expected + ('\n' if name.endswith('.txt') else '')
    assert QApplication.clipboard().text() == expected
    assert editor.toPlainText() == expected_after_paste
    assert tabs.save_editor(editor, autosave=True)
    assert path.read_text(encoding='utf-8') == expected
    assert EditorTabs().open_file(path).toPlainText() == expected
    assert expected.count('\t') == text.count('\t')
    editor.autosave_timer.stop()


def test_open_context_compacts_all_zero_character_lines(tmp_path):
    app()
    raw = '# Settings\n\nkeep\n\n# Novel Text\n\nA\n\nB\n\n# Glossary\n\n' + VOCAB
    expected = '# Settings\n\nkeep\n\n# Novel Text\nA\nB\n# Glossary\n\n' + VOCAB
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
    assert export.editor.toPlainText() == 'previous\nnext\nlast\n'
    export.editor.undo(); assert export.editor.toPlainText() == 'previous'


def test_open_context_compacts_fence_and_paste_without_changing_characters(tmp_path):
    app()
    raw = '# Novel Text\n\nA\n\n```json\n{\n\n}\n```\n\nB\n\n# Settings\n\nold'
    expected = '# Novel Text\nA\n```json\n{\n\n}\n```\nB\n# Settings\n\nold'
    path = tmp_path / 'Context.md'; path.write_text(raw, encoding='utf-8')
    tabs = EditorTabs(); editor = tabs.open_file(path)
    assert editor.toPlainText() == expected
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    data = QMimeData(); data.setText('\n\nnew\n\nvalue')
    editor.insertFromMimeData(data)
    assert editor.toPlainText() == expected + '\nnew\nvalue\n'
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
    assert QApplication.clipboard().text() == '{\n\n}'


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


@pytest.mark.parametrize('text', [
    'คำแปลภาษาไทย',
    '冷却流道 ช่องทางไหลของสารหล่อเย็น',
    'ศัพท์\tคำแปล\tหมายเหตุ',
    '[A]\n[จบตอน]',
    'มีช่องว่าง  และ\tแท็บ\u3000ยูนิโค้ด',
])
def test_paste_at_document_end_prepares_one_line_and_undoes_together(text):
    app()
    editor = CodeEditor()
    editor.setProperty('autoNewlineOnPaste', True)
    editor.setPlainText('previous')
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    mime = QMimeData(); mime.setText(text)
    editor.insertFromMimeData(mime)
    expected = 'previous' + text + ('\n' if not text.endswith(('\n', '\r', '\u2028', '\u2029', '\u0085')) else '')
    assert editor.toPlainText() == expected
    editor.undo()
    assert editor.toPlainText() == 'previous'
    editor.redo()
    assert editor.toPlainText() == expected


def test_paste_uses_existing_next_line_without_adding_blank_line():
    app()
    editor = CodeEditor(); editor.setPlainText('first\nsecond')
    editor.setProperty('autoNewlineOnPaste', True)
    cursor = editor.textCursor(); cursor.setPosition(len('first'))
    editor.setTextCursor(cursor)
    mime = QMimeData(); mime.setText(' pasted')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == 'first pasted\nsecond'


def test_paste_that_already_ends_with_newline_does_not_add_another():
    app()
    editor = CodeEditor(); editor.setProperty('autoNewlineOnPaste', True)
    editor.setPlainText('previous')
    editor.moveCursor(editor.textCursor().MoveOperation.End)
    mime = QMimeData(); mime.setText('new line\n')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == 'previousnew line\n'
    editor.undo()
    assert editor.toPlainText() == 'previous'


def test_paste_in_middle_does_not_add_a_newline():
    app()
    editor = CodeEditor(); editor.setPlainText('before after')
    editor.setProperty('autoNewlineOnPaste', True)
    cursor = editor.textCursor(); cursor.setPosition(len('before '))
    editor.setTextCursor(cursor)
    mime = QMimeData(); mime.setText('pasted')
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == 'before pastedafter'


@pytest.mark.parametrize("count", [1, 10, 20])
def test_rapid_paste_preserves_chapter_boundaries_and_undo(tmp_path, count):
    app()
    export = panel(tmp_path)
    editor = export.editor
    editor.setProperty("autoNewlineOnPaste", False)
    for index in range(count):
        mime = QMimeData()
        mime.setText(f"บทที่ {475 + index} 内容ไทย中文")
        editor.insertFromMimeData(mime)
    expected = "\n".join(f"บทที่ {475 + index} 内容ไทย中文" for index in range(count))
    assert editor.toPlainText() == expected
    for _ in range(count):
        editor.undo()
    assert editor.toPlainText() == ""
    for _ in range(count):
        editor.redo()
    assert editor.toPlainText() == expected


def test_rapid_paste_at_explicit_midline_never_inserts_separator(tmp_path):
    app()
    editor = panel(tmp_path).editor
    editor.setProperty("autoNewlineOnPaste", False)
    editor.setPlainText("ABCD")
    cursor = editor.textCursor()
    cursor.setPosition(2)
    editor.setTextCursor(cursor)
    mime = QMimeData(); mime.setText("中文ไทย")
    editor.insertFromMimeData(mime)
    assert editor.toPlainText() == "AB中文ไทยCD"
    editor.undo()
    assert editor.toPlainText() == "ABCD"


def test_txt_export_and_file_editor_paste_boundary_without_extra_blank_lines(tmp_path):
    app()
    path = tmp_path / "WSTContext.md"
    path.write_text("", encoding="utf-8")
    tabs = EditorTabs()
    editor = tabs.open_file(path)
    for text in ("บทที่ 474\n正文", "บทที่ 475\nภาษาไทย"):
        mime = QMimeData(); mime.setText(text)
        editor.insertFromMimeData(mime)
    assert editor.toPlainText() == "บทที่ 474\n正文\nบทที่ 475\nภาษาไทย\n"
    assert tabs.save_editor(editor)
    assert path.read_text(encoding="utf-8") == editor.toPlainText()[:-1]
