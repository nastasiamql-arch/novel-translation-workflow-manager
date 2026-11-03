"""Selection must be read-only and independent of the lazy batch list."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.translation_batch_page import TranslationBatchPage
from novel_workflow.vocabulary_batch_page import TxtVocabularyPage


def _chapters(folder, count):
    folder.mkdir()
    for number in range(1, count + 1):
        (folder / f"{number:04d} ไทย中文.txt").write_text("text", encoding="utf-8")


def test_vocabulary_selection_is_read_only_and_restores_only_same_source(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / 'source'
    other = tmp_path / 'other'
    _chapters(source, 90)
    _chapters(other, 90)
    saved = {}
    page = TxtVocabularyPage({'folder': str(source), 'batch_size': 1},
                             lambda state: saved.update(state), source)
    page.resize(1400, 800)
    page.show()
    app.processEvents()
    QApplication.clipboard().setText('unchanged')
    page._scroll_to_group(page._groups[85])
    app.processEvents()
    app.processEvents()
    app.processEvents()
    row = page._batch_widgets[85]
    y = row.mapTo(page.scroll.viewport(), row.rect().topLeft()).y()
    assert 0 <= y < page.scroll.viewport().height()
    height = row.height()
    QTest.mouseClick(row, Qt.LeftButton)
    app.processEvents()
    assert page._selected_group.index == 86
    assert '0086 ไทย中文.txt' in page.batch_workspace.text.toPlainText()
    assert row.height() == height
    assert QApplication.clipboard().text() == 'unchanged'
    assert saved['selected_batch']['index'] == 86
    scroll_before = page.scroll.verticalScrollBar().value()
    assert scroll_before > 0
    page.close()
    reopened = TxtVocabularyPage(saved, lambda state: None, source)
    reopened.resize(1400, 800)
    reopened.show()
    QTest.qWait(300)
    assert reopened._selected_group.index == 86
    assert reopened.scroll.verticalScrollBar().value() == scroll_before
    reopened.batch_size.setValue(2)
    assert reopened._selected_group.index == 1
    reopened.history_filter.setCurrentIndex(reopened.history_filter.findData('copied'))
    assert reopened._selected_group is None
    assert not reopened.batch_workspace.copy.isEnabled()
    reopened.history_filter.setCurrentIndex(reopened.history_filter.findData('all'))
    assert reopened._selected_group.index == 1
    reopened.state['folder'] = str(other)
    reopened.refresh()
    assert reopened._selected_group.index == 1
    assert reopened._source_identity != saved['selected_batch']['source']
    reopened.close()
    QApplication.clipboard().clear()


def test_translation_selection_and_navigation_do_not_copy(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / 'source'
    _chapters(source, 90)
    repo = ProjectRepository(tmp_path / 'repo')
    profile = NovelProfile()
    saved = {}
    page = TranslationBatchPage(repo, lambda: profile, object(),
                                {'mode': 'folder', 'path': str(source), 'size': 1},
                                lambda state: saved.update(state), lambda: None)
    page.resize(1400, 800)
    page.show()
    try:
        assert page._load_worker.wait(20000)
        app.processEvents()
        QApplication.clipboard().setText('unchanged')
        page._scroll_to_group(page._groups[85])
        app.processEvents()
        app.processEvents()
        app.processEvents()
        row = page._row_widgets[86][1]
        y = row.mapTo(page.scroll.viewport(), row.rect().topLeft()).y()
        assert 0 <= y < page.scroll.viewport().height()
        height = row.height()
        QTest.keyClick(row, Qt.Key_Space)
        app.processEvents()
        assert page._selected_group.index == 86
        assert '0086 ไทย中文.txt' in page.batch_workspace.text.toPlainText()
        assert row.height() == height
        assert QApplication.clipboard().text() == 'unchanged'
        assert saved['selected_batch']['index'] == 86
        QTest.keyClick(row, Qt.Key_Down)
        assert page._selected_group.index == 87
        assert QApplication.clipboard().text() == 'unchanged'
    finally:
        if page._copy_worker and page._copy_worker.isRunning():
            page._copy_worker.wait(20000)
        page.close()
        app.processEvents()
        QApplication.clipboard().clear()


def test_vocabulary_1000_batches_remain_lazy_and_select_last(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / 'many'
    _chapters(source, 1000)
    page = TxtVocabularyPage({'folder': str(source), 'batch_size': 1},
                             lambda state: None, source)
    page.resize(1400, 800)
    page.show()
    app.processEvents()
    assert len(page._groups) == 1000
    assert len(page._batch_widgets) == 36
    page._scroll_to_group(page._groups[-1])
    app.processEvents()
    app.processEvents()
    app.processEvents()
    assert page._selected_group.index == 1000
    assert '1000 ไทย中文.txt' in page.batch_workspace.text.toPlainText()
    assert len(page._batch_widgets) == 1000
    assert page._batch_widgets[-1].height() == page._batch_widgets[0].height()
    y = page._batch_widgets[-1].mapTo(page.scroll.viewport(), page._batch_widgets[-1].rect().topLeft()).y()
    assert 0 <= y < page.scroll.viewport().height()
    page.close()
    app.processEvents()


def test_workspace_switches_to_list_and_detail_views_when_narrow(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / 'source'
    _chapters(source, 2)
    page = TxtVocabularyPage({'folder': str(source), 'batch_size': 1},
                             lambda state: None, source)
    page.resize(900, 600)
    page.show()
    app.processEvents()
    workspace = page.batch_workspace
    copy_button = page._copy_buttons[0][0]
    assert copy_button.mapTo(page.scroll.viewport(), copy_button.rect().topRight()).x() <= page.scroll.viewport().width()
    workspace.setFixedWidth(450)
    app.processEvents()
    assert workspace._narrow
    QTest.mouseClick(page._batch_widgets[1], Qt.LeftButton)
    assert page._selected_group.index == 2
    assert not workspace.list_widget.isVisible()
    assert workspace.detail.isVisible()
    workspace.back.click()
    assert workspace.list_widget.isVisible()
    page.close()
    app.processEvents()
