import shutil
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QListWidget, QHBoxLayout, QPushButton, QFileDialog, QMessageBox

from ..downloader.registry import SourceRegistry


class SourceManagerDialog(QDialog):
    sources_changed = Signal()

    def __init__(self, sources_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("จัดการแหล่งต้นฉบับ")
        self.resize(540, 420)
        self.sources_dir = Path(sources_dir)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("แหล่งที่มาพร้อมโปรแกรมและเว็บที่ตั้งค่าด้วย JSON"))
        self.list = QListWidget()
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        for label, callback in (("โหลดใหม่", self.reload), ("นำเข้า JSON", self.import_json),
                                ("เปิดโฟลเดอร์", self.open_folder), ("ทดสอบ URL", self.test_url)):
            button = QPushButton(label)
            button.clicked.connect(callback)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.reload()

    def reload(self):
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        self.list.clear()
        self.list.addItem("✓ TomatoMTL · Chinese Raw / 原文")
        registry = SourceRegistry.builtins(self.sources_dir)
        for source in registry.list_sources():
            if source.id != "tomatomtl": self.list.addItem(f"{source.name} · {source.id}")
        for error in registry.load_errors:
            self.list.addItem(f"⚠ {error}")

    def import_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "นำเข้า Source JSON", str(self.sources_dir), "JSON (*.json)")
        if not path: return
        try:
            from ..downloader.sources.configurable import ConfigurableSource
            import json
            value = json.loads(Path(path).read_text(encoding="utf-8"))
            source = ConfigurableSource.validate(value)
            target = self.sources_dir / f"{source['id']}.json"
            if target.exists(): raise ValueError(f"มี source id นี้แล้ว: {source['id']}")
            shutil.copy2(path, target)
            self.reload()
            self.sources_changed.emit()
        except Exception as exc:
            QMessageBox.warning(self, "นำเข้าไม่สำเร็จ", str(exc))

    def open_folder(self):
        self.sources_dir.mkdir(parents=True, exist_ok=True)
        import os
        os.startfile(str(self.sources_dir))

    def test_url(self):
        from PySide6.QtWidgets import QInputDialog
        url, ok = QInputDialog.getText(self, "ทดสอบแหล่งต้นฉบับ", "URL ของหนังสือ:")
        if not ok or not url: return
        try:
            source = SourceRegistry.builtins(self.sources_dir).match(url)
        except Exception as exc:
            QMessageBox.warning(self, "ไม่พบแหล่งต้นฉบับ", str(exc))
            return
        from ..downloader.worker import DownloaderWorker
        self.test_worker = DownloaderWorker(lambda cancel, progress: source.get_book(url), self)
        self.test_worker.completed.connect(lambda book: QMessageBox.information(self, "ทดสอบสำเร็จ", f"{source.name}\n{book.title}\n{book.total_chapters} ตอน"))
        self.test_worker.failed.connect(lambda message: self._test_failed(message, url))
        self.test_worker.start()

    def _test_failed(self, message, url):
        if "anti-bot challenge" not in message.casefold():
            QMessageBox.warning(self, "ทดสอบไม่สำเร็จ", message)
            return
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("เว็บขอให้ยืนยันว่าเป็นผู้ใช้")
        dialog.setText(message)
        open_button = dialog.addButton("เปิดหน้าเว็บใน Browser", QMessageBox.AcceptRole)
        dialog.addButton(QMessageBox.Ok)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(url))

    def closeEvent(self, event):
        worker = getattr(self, "test_worker", None)
        if worker and worker.isRunning():
            QMessageBox.information(self, "กำลังทดสอบ", "รอให้การทดสอบแหล่งต้นฉบับเสร็จก่อนปิดหน้าต่าง")
            event.ignore()
            return
        event.accept()
