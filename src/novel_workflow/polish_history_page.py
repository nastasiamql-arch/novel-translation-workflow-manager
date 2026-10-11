"""Full-page history using the shell's navigation and existing theme tokens."""
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QFrame, QMenu, QInputDialog, QMessageBox, QApplication)


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
        subtitle = QLabel('เลือกช่วงบทเพื่อคัดลอกไฟล์กลับมาใช้งาน · ใช้ Context ที่บันทึกไว้ในเวลานั้น')
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
        self.card_layout.setContentsMargins(0, 4, 0, 4); self.card_layout.setSpacing(12)
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
        for snapshot in found:
            card = QFrame(); card.setObjectName('settingsCard')
            rows = QVBoxLayout(card); rows.setContentsMargins(16, 14, 16, 14)
            top = QHBoxLayout()
            title = QLabel('บท ' + str(snapshot.manifest.get('chapter_range', 'ไม่ทราบช่วงบท')).replace('-', '–'))
            title.setObjectName('historyRangeTitle'); title.setWordWrap(True); top.addWidget(title, 1)
            copy = QPushButton('คัดลอก'); copy.setObjectName('polishHistoryCopy')
            copy.setEnabled(not snapshot.error)
            copy.setAccessibleName(title.text() + ' คัดลอกไฟล์ทั้งหมด')
            copy.clicked.connect(lambda _=False, s=snapshot: self.owner.copy_history_snapshot(self.profile, s))
            top.addWidget(copy)
            more = QPushButton('⋯'); more.setAccessibleName(title.text() + ' ตัวเลือกเพิ่มเติม')
            more.clicked.connect(lambda _=False, s=snapshot, b=more: self.more_menu(s, b))
            top.addWidget(more); rows.addLayout(top)
            try: stamp = datetime.fromisoformat(snapshot.manifest['created_at']).astimezone().strftime('%d/%m/%Y · %H:%M:%S')
            except (KeyError, ValueError, TypeError): stamp = snapshot.path.name
            detail = QLabel(f'{stamp} · {snapshot.manifest.get("file_count", 0) if not snapshot.error else "?"} ไฟล์'
                            f' · {snapshot.manifest.get("step_name", "")}')
            detail.setWordWrap(True); detail.setObjectName('mutedLabel'); rows.addWidget(detail)
            if snapshot.error:
                error = QLabel('ตรวจพบข้อผิดพลาด: ' + snapshot.error); error.setWordWrap(True)
                rows.addWidget(error)
            if snapshot.warning:
                warning = QLabel(snapshot.warning); warning.setWordWrap(True)
                rows.addWidget(warning)
            self.card_layout.addWidget(card)
        if not found:
            empty = QLabel('ยังไม่มีประวัติ\nเลือกขั้นตอนใน Settings แล้วคลิกขั้นตอนเพื่อบันทึกไฟล์'
                           if not self.snapshots else 'ไม่พบช่วงบทที่ค้นหา')
            empty.setWordWrap(True); empty.setObjectName('emptyStateDescription'); self.card_layout.addWidget(empty)
        self.card_layout.addStretch()

    def more_menu(self, snapshot, button):
        menu = QMenu(button)
        rename = menu.addAction('แก้ไขช่วงบท'); rename.setEnabled(not snapshot.error)
        open_folder = menu.addAction('เปิดโฟลเดอร์')
        verify = menu.addAction('ตรวจสอบไฟล์อีกครั้ง')
        delete = menu.addAction('ลบประวัติ…')
        action = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if action == open_folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(snapshot.path)))
        elif action == verify: self.refresh()
        elif action == rename:
            value, accepted = QInputDialog.getText(self, 'แก้ไขช่วงบท', 'ช่วงบท เช่น 6-10', text=snapshot.manifest['chapter_range'])
            if accepted:
                mime = QApplication.clipboard().mimeData()
                urls = [u.toLocalFile() for u in mime.urls()] if mime else []
                self.owner.run_history_job(lambda: self.owner.polish_history.rename(self.profile, snapshot.path, value, clipboard_paths=urls),
                                           lambda _: self.refresh(), self.failed)
        elif action == delete:
            if QMessageBox.question(self, 'ลบประวัติ', 'ลบประวัติที่เลือกและไฟล์สำรองทั้งหมด?',
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
                mime = QApplication.clipboard().mimeData()
                urls = [u.toLocalFile() for u in mime.urls()] if mime else []
                self.owner.run_history_job(lambda: self.owner.polish_history.delete(self.profile, snapshot.path, urls),
                                           lambda _: self.refresh(), self.failed)
