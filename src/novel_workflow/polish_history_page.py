"""Full-page history using the shell's navigation and existing theme tokens."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QMenu, QInputDialog, QMessageBox, QApplication, QStyle)


class HistoryWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(object)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try: self.succeeded.emit(self.operation())
        except Exception as exc: self.failed.emit(exc)


class PolishHistoryPage(QWidget):
    def __init__(self, owner, profile):
        super().__init__(owner)
        self.owner, self.profile = owner, profile
        self.snapshots = []
        self._refresh_queued = False
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        subtitle = QLabel('ไฟล์ตามที่ผูกไว้กับขั้นตอนตรวจคำแปล · เลือกคัดลอกหรือระบุช่วงบทภายหลัง')
        subtitle.setWordWrap(True); subtitle.setObjectName('mutedLabel'); layout.addWidget(subtitle)
        tools = QHBoxLayout()
        self.search = QLineEdit(); self.search.setPlaceholderText('ค้นหาเลขบทหรือช่วงบท…')
        self.search.setAccessibleName('ค้นหาประวัติช่วงบท')
        self.search.textChanged.connect(self.render); tools.addWidget(self.search, 1)
        self.refresh_button = QPushButton('Refresh'); self.refresh_button.clicked.connect(self.refresh)
        tools.addWidget(self.refresh_button); layout.addLayout(tools)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.cards = QWidget(); self.cards.setObjectName('polishHistoryCards')
        self.card_layout = QVBoxLayout(self.cards)
        self.card_layout.setContentsMargins(0, 2, 0, 2); self.card_layout.setSpacing(4)
        scroll.setWidget(self.cards); layout.addWidget(scroll, 1)

    def refresh(self):
        if self.owner._history_pending:
            self.status.setText('กำลังรอการบันทึกประวัติ…')
            if not self._refresh_queued and self.owner._history_workers:
                self._refresh_queued = True
                def after_job():
                    self._refresh_queued = False
                    self.refresh()
                self.owner._history_workers[-1].finished.connect(after_job)
            return
        self.status.setText('กำลังตรวจสอบไฟล์และ Hash…')
        mime = QApplication.clipboard().mimeData()
        urls = [u.toLocalFile() for u in mime.urls()] if mime else []
        self.owner.run_history_job(lambda: self.owner.polish_history.list(self.profile, clipboard_paths=urls), self.loaded, self.failed)

    def loaded(self, snapshots):
        self.snapshots = snapshots
        count = sum(x.manifest.get('file_count', 0) for x in snapshots if not x.error)
        size = sum(sum(e['size'] for e in x.manifest['files']) for x in snapshots if not x.error)
        self.status.setText(f'{len(snapshots)} ประวัติ · {count} ไฟล์ · {size / (1024 * 1024):,.2f} MB')
        self.render()

    def failed(self, error):
        self.status.setText(str(error))

    def render(self, *_):
        while self.card_layout.count():
            item = self.card_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        query = self.search.text().strip().replace('–', '-')
        found = []
        for snapshot in self.snapshots:
            span = str(snapshot.manifest.get('chapter_range', ''))
            match = not query or query in span
            if query.isdigit() and span:
                try:
                    bounds = [int(x) for x in span.split('-')]
                    match = bounds[0] <= int(query) <= bounds[-1]
                except (ValueError, TypeError): pass
            if match: found.append(snapshot)
        # Visible ordinal labels are continuous even after deletion. The
        # manifest history_number remains a durable internal identity.
        visible_numbers = {
            item.path: len(self.snapshots) - index
            for index, item in enumerate(self.snapshots)
        }
        for snapshot in found:
            card = QFrame(); card.setObjectName('polishHistoryRow')
            rows = QHBoxLayout(card); rows.setContentsMargins(8, 4, 8, 4); rows.setSpacing(6)
            card.setMinimumHeight(54)
            text_column = QVBoxLayout(); text_column.setSpacing(0)
            rows.addLayout(text_column, 1)
            top = QHBoxLayout()
            span = snapshot.manifest.get('chapter_range')
            title = QLabel(('บท ' + str(span).replace('-', '–')) if span else 'รอระบุช่วงบท')
            number = visible_numbers[snapshot.path]
            title.setObjectName('historyRangeTitle'); title.setWordWrap(True); text_column.addWidget(title)
            # Keep the chapter label uncluttered. Display the current list
            # number alongside its action so the copy target is easy to find.
            sequence = QLabel(f'[{number:03d}]')
            sequence.setObjectName('historySequenceNumber')
            sequence.setAlignment(Qt.AlignCenter)
            sequence.setFixedWidth(64)
            sequence.setMinimumHeight(34)
            sequence.setToolTip('ลำดับรายการในประวัติ')
            sequence.setAccessibleName(f'ประวัติหมายเลข {number:03d}')
            rows.addWidget(sequence)
            copy = QPushButton('คัดลอก'); copy.setObjectName('polishHistoryCopy')
            changed_payload = snapshot.error.startswith('ไฟล์ในประวัติถูกแก้ไขหรือ Hash ไม่ตรง:')
            copy.setEnabled(not snapshot.error or changed_payload)
            if changed_payload:
                copy.setToolTip('ไฟล์ในประวัติถูกแก้ไข · คลิกเพื่อยืนยันไฟล์ที่แก้แล้วและคัดลอก')
            copy.setAccessibleName(sequence.text() + ' ' + title.text() + ' คัดลอกไฟล์ทั้งหมด')
            copy.clicked.connect(lambda _=False, s=snapshot: self.copy_snapshot(s))
            rows.addWidget(copy)
            delete = QPushButton(); delete.setObjectName('polishHistoryDelete')
            delete.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
            delete.setToolTip('ลบประวัตินี้ไปยังถังรีไซเคิล')
            delete.setAccessibleName(sequence.text() + ' ' + title.text() + ' ลบประวัตินี้ไปยังถังรีไซเคิล')
            delete.setFixedWidth(32)
            delete.setStyleSheet('QPushButton:hover { background: #f6caca; color: #782020; }')
            delete.clicked.connect(lambda _=False, s=snapshot, b=delete: self.delete_snapshot(s, b))
            rows.addWidget(delete)
            more = QPushButton('⋯'); more.setAccessibleName(sequence.text() + ' ' + title.text() + ' ตัวเลือกเพิ่มเติม')
            more.clicked.connect(lambda _=False, s=snapshot, b=more: self.more_menu(s, b))
            more.setFixedWidth(28); rows.addWidget(more)
            try: stamp = datetime.fromisoformat(snapshot.manifest['created_at']).astimezone().strftime('%H:%M')
            except (KeyError, ValueError, TypeError): stamp = snapshot.path.name
            review_status = snapshot.manifest.get('review_status', 'รอตรวจ')
            detail = QLabel(f'{stamp} · {snapshot.manifest.get("file_count", 0) if not snapshot.error else "?"} ไฟล์ · {review_status}')
            detail.setWordWrap(True); detail.setObjectName('mutedLabel'); text_column.addWidget(detail)
            if snapshot.error:
                error = QLabel('ตรวจพบข้อผิดพลาด: ' + snapshot.error); error.setWordWrap(True)
                text_column.addWidget(error)
            if snapshot.warning:
                warning = QLabel(snapshot.warning); warning.setWordWrap(True)
                text_column.addWidget(warning)
            self.card_layout.addWidget(card)
        if not found:
            empty = QLabel('ยังไม่มีประวัติ\nเลือกขั้นตอนใน Settings แล้วคลิกขั้นตอนเพื่อบันทึกไฟล์'
                           if not self.snapshots else 'ไม่พบช่วงบทที่ค้นหา')
            empty.setWordWrap(True); empty.setObjectName('emptyStateDescription'); self.card_layout.addWidget(empty)
        self.card_layout.addStretch()

    def copy_snapshot(self, snapshot):
        """Only explicitly confirmed historical edits may update stored hashes."""
        if not snapshot.error:
            self.owner.copy_history_snapshot(self.profile, snapshot)
            return
        if not snapshot.error.startswith('ไฟล์ในประวัติถูกแก้ไขหรือ Hash ไม่ตรง:'):
            self.failed('ไฟล์ประวัติเสียหายหรือหายไป ไม่สามารถคัดลอกได้')
            return
        confirmation = QMessageBox.question(
            self, 'ยืนยันไฟล์ที่แก้ไขในประวัติ',
            'ไฟล์สำรองในประวัติชุดนี้ถูกแก้ไขหลังบันทึก\\n\\n'
            'หากคุณแก้ไขไฟล์นี้โดยตั้งใจ ให้กด Yes เพื่อเก็บ Hash เดิม'
            ' ไว้เป็นประวัติ ตรวจไฟล์ที่แก้ใหม่ แล้วคัดลอก\\n\\n'
            'หากไม่ได้แก้เอง ให้กด No และตรวจไฟล์ก่อน',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        zipped = self.owner.settings.copy_files_as_zip
        def operation():
            modified = self.owner.polish_history.accept_snapshot_edits(
                self.profile, snapshot.path
            )
            paths = self.owner.polish_history.clipboard_paths(
                self.profile, snapshot.path, zipped=zipped
            )
            count = len(paths)
            if zipped:
                import zipfile
                with zipfile.ZipFile(paths[0]) as archive:
                    count = sum(not item.is_dir() for item in archive.infolist())
            return paths, count, modified
        def success(result):
            paths, count, modified = result
            self.owner._history_clipboard(paths, count, zipped)
            self.refresh()
        self.owner.run_history_job(operation, success, self.failed)

    def delete_snapshot(self, snapshot, button=None):
        if self.owner.history_busy():
            self.status.setText('กำลังจัดการประวัติ กรุณารอสักครู่')
            return
        mime = QApplication.clipboard().mimeData()
        urls = [u.toLocalFile() for u in mime.urls()] if mime else []
        if button: button.setEnabled(False)
        def failed(error):
            if button: button.setEnabled(True)
            self.failed('ลบประวัติไม่สำเร็จ: ' + str(error))
        def deleted(_):
            self.status.setText('ย้ายประวัติไปยังถังรีไซเคิลแล้ว · Clipboard คงเดิม')
            self.refresh()
        self.owner.run_history_job(lambda: self.owner.polish_history.delete(self.profile, snapshot.path, urls),
                                   deleted, failed)

    def more_menu(self, snapshot, button):
        menu = QMenu(button)
        rename = menu.addAction('แก้ไขช่วงบท'); rename.setEnabled(not snapshot.error)
        status = menu.addAction('ทำเครื่องหมายตรวจแล้ว' if snapshot.manifest.get('review_status', 'รอตรวจ') == 'รอตรวจ'
                                else 'ตั้งเป็นรอตรวจ')
        status.setEnabled(not snapshot.error)
        open_folder = menu.addAction('เปิดโฟลเดอร์')
        verify = menu.addAction('ตรวจสอบไฟล์อีกครั้ง')
        delete = menu.addAction('ลบประวัติไปยังถังรีไซเคิล')
        action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if action == open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(snapshot.path)))
        elif action == verify: self.refresh()
        elif action == status:
            target = 'ตรวจแล้ว' if snapshot.manifest.get('review_status', 'รอตรวจ') == 'รอตรวจ' else 'รอตรวจ'
            self.owner.run_history_job(lambda: self.owner.polish_history.set_review_status(self.profile, snapshot.path, target),
                                       lambda _: self.refresh(), self.failed)
        elif action == rename:
            value, accepted = QInputDialog.getText(self, 'ระบุช่วงบท', 'ช่วงบท เช่น 6-10', text=snapshot.manifest.get('chapter_range') or '')
            if accepted:
                mime = QApplication.clipboard().mimeData()
                urls = [u.toLocalFile() for u in mime.urls()] if mime else []
                self.owner.run_history_job(lambda: self.owner.polish_history.rename(self.profile, snapshot.path, value, clipboard_paths=urls),
                                           lambda _: self.refresh(), self.failed)
        elif action == delete:
            self.delete_snapshot(snapshot)
