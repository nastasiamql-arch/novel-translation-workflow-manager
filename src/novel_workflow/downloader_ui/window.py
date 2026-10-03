from __future__ import annotations

from datetime import date
from pathlib import Path
import subprocess
import tempfile

from PySide6.QtCore import QThread, QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QProgressDialog, QPushButton, QSplitter, QVBoxLayout, QWidget,
                               QApplication)

from .. import __version__
from ..downloader.registry import SourceRegistry
from ..downloader.service import DownloadService
from ..downloader.storage import DownloaderRepository
from ..downloader.worker import DownloaderWorker
from ..updater import UpdateError, UpdateInfo, check_for_update, download_update
from .panel import DownloaderBookPanel


class _UpdateCheckWorker(QThread):
    finished_check = Signal(object, object)

    def run(self):
        try:
            self.finished_check.emit(check_for_update(__version__, installer_prefix="NovelDownloader"), None)
        except UpdateError as exc:
            self.finished_check.emit(None, str(exc))


class _UpdateDownloadWorker(QThread):
    progress = Signal(int)
    finished_download = Signal(object, object)

    def __init__(self, update: UpdateInfo, destination: Path, parent=None):
        super().__init__(parent)
        self.update = update
        self.destination = destination

    def run(self):
        try:
            result = download_update(self.update, self.destination,
                                    progress=self.progress.emit,
                                    cancelled=self.isInterruptionRequested)
            self.finished_download.emit(result, None)
        except UpdateError as exc:
            self.finished_download.emit(None, str(exc))


class DownloaderWindow(QMainWindow):
    def __init__(self, repository: DownloaderRepository | None = None):
        super().__init__()
        self.setWindowTitle("Novel Downloader")
        self.resize(1120, 740)
        self.repository = repository or DownloaderRepository()
        self.registry = SourceRegistry.builtins(self.repository.sources_dir)
        self.service = DownloadService(self.repository, self.registry)
        self.add_worker = None
        self._update_check_worker = None
        self._update_download_worker = None
        self._update_progress = None

        root = QWidget()
        layout = QVBoxLayout(root)
        header = QHBoxLayout()
        title = QLabel("Novel Downloader")
        title.setObjectName("pageTitle")
        header.addWidget(title, 1)
        self.output_root_label = QLabel()
        self.output_root_label.setObjectName("mutedLabel")
        header.addWidget(self.output_root_label)
        self.output_root_button = QPushButton("โฟลเดอร์ส่งออก")
        self.output_root_button.clicked.connect(self.choose_output_root)
        header.addWidget(self.output_root_button)
        self.update_button = QPushButton("ตรวจสอบอัปเดต")
        self.update_button.clicked.connect(self.check_updates)
        header.addWidget(self.update_button)
        self.add_button = QPushButton("＋ เพิ่มจาก URL")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self.add_book)
        header.addWidget(self.add_button)
        layout.addLayout(header)

        self.description = QLabel(
            "รายการและค่าตั้งต้นจัดเก็บแยกจาก Palantir: Novel · ไฟล์จะส่งออกไปยังโฟลเดอร์ที่คุณเลือก"
        )
        self.description.setObjectName("mutedLabel")
        layout.addWidget(self.description)

        splitter = QSplitter(Qt.Horizontal)
        self.books_list = QListWidget()
        self.books_list.setMinimumWidth(220)
        self.books_list.currentItemChanged.connect(self._select_book)
        splitter.addWidget(self.books_list)
        self.panel = DownloaderBookPanel(self)
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)
        self.setCentralWidget(root)

        self.refresh_books()
        if self.repository.load_settings().get("last_update_check_date") != date.today().isoformat():
            QTimer.singleShot(2500, lambda: self.check_updates(manual=False))

    def output_root(self) -> str:
        return str(self.repository.load_settings().get("output_root", ""))

    def choose_output_root(self):
        settings = self.repository.load_settings()
        chosen = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์หลักสำหรับไฟล์ที่ดาวน์โหลด",
            settings.get("output_root", ""),
        )
        if not chosen:
            return
        settings["output_root"] = chosen
        self.repository.save_settings(settings)
        self._refresh_output_root_label()

    def _refresh_output_root_label(self):
        value = self.output_root()
        self.output_root_label.setText(f"จัดเก็บที่: {value}" if value else "ยังไม่ได้เลือกโฟลเดอร์ส่งออก")

    def add_book(self):
        url, accepted = QInputDialog.getText(self, "เพิ่มนิยายจาก URL", "URL หนังสือต้นฉบับ:")
        if not accepted or not url.strip():
            return
        output_root = self.output_root()
        if not output_root:
            output_root = QFileDialog.getExistingDirectory(
                self, "เลือกโฟลเดอร์หลักสำหรับไฟล์ที่ดาวน์โหลด"
            )
            if not output_root:
                return
            settings = self.repository.load_settings()
            settings["output_root"] = output_root
            self.repository.save_settings(settings)
            self._refresh_output_root_label()

        self.add_button.setEnabled(False)
        self._pending_url = url.strip()
        worker = DownloaderWorker(
            lambda _cancel, _progress: self.service.add_book(self._pending_url, output_root), self
        )
        self.add_worker = worker
        worker.completed.connect(self._book_added)
        worker.failed.connect(self._add_failed)
        worker.finished.connect(lambda: self.add_button.setEnabled(True))
        worker.start()

    def _book_added(self, result):
        book, info = result
        self.refresh_books(book.id)
        self.statusBar().showMessage(f"เพิ่ม {info.title} แล้ว · {info.total_chapters} ตอน", 8000)

    def _add_failed(self, message):
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("เพิ่มนิยายไม่สำเร็จ")
        dialog.setText(message)
        if "anti-bot challenge" in message.casefold():
            open_button = dialog.addButton("เปิดหน้าเว็บใน Browser", QMessageBox.AcceptRole)
            dialog.addButton(QMessageBox.Ok)
            dialog.exec()
            if dialog.clickedButton() is open_button:
                QDesktopServices.openUrl(QUrl(self._pending_url))
            return
        dialog.exec()

    def _select_book(self, current, _previous=None):
        if current is None:
            self.panel.set_book(None)
            return
        book_id = current.data(Qt.UserRole)
        self.panel.set_book(self.repository.get_book(book_id))

    def selected_book_id(self):
        item = self.books_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def refresh_books(self, select_id=None):
        previous = select_id or self.selected_book_id()
        self.books_list.blockSignals(True)
        self.books_list.clear()
        selected = None
        for book in self.repository.list_books():
            item = QListWidgetItem(book.title)
            item.setData(Qt.UserRole, book.id)
            binding = book.source_binding
            item.setToolTip(binding.book_url if binding else "ยังไม่ผูก URL")
            self.books_list.addItem(item)
            if book.id == previous:
                selected = item
        self.books_list.blockSignals(False)
        if selected:
            self.books_list.setCurrentItem(selected)
            self.panel.set_book(self.repository.get_book(selected.data(Qt.UserRole)))
        else:
            self.books_list.clearSelection()
            self.panel.set_book(None)
        self._refresh_output_root_label()

    def reload_sources(self):
        self.registry = SourceRegistry.builtins(self.repository.sources_dir)
        self.service = DownloadService(self.repository, self.registry)

    def check_updates(self, checked=False, manual=True):
        if self._update_check_worker and self._update_check_worker.isRunning():
            if manual:
                QMessageBox.information(self, "อัปเดต", "กำลังตรวจสอบอัปเดตอยู่ครับ")
            return
        worker = _UpdateCheckWorker(self)
        self._update_check_worker = worker

        def complete(update, error):
            self._update_check_worker = None
            if error:
                if manual:
                    QMessageBox.warning(self, "ตรวจสอบอัปเดตไม่ได้", error)
                return
            settings = self.repository.load_settings()
            settings["last_update_check_date"] = date.today().isoformat()
            self.repository.save_settings(settings)
            if update is None:
                if manual:
                    QMessageBox.information(self, "อัปเดต", f"คุณใช้เวอร์ชันล่าสุดแล้ว (v{__version__})")
                return
            self._offer_update(update)

        worker.finished_check.connect(complete)
        worker.start()

    def _offer_update(self, update: UpdateInfo):
        dialog = QMessageBox(self)
        dialog.setWindowTitle("มี Novel Downloader เวอร์ชันใหม่")
        dialog.setText(
            f"เวอร์ชันปัจจุบัน: v{__version__}\nเวอร์ชันใหม่: v{update.version}\n\n"
            f"{update.notes[:1600] if update.notes else 'ไม่มีรายละเอียดการเปลี่ยนแปลง'}"
        )
        install = dialog.addButton("อัปเดตเลย", QMessageBox.AcceptRole)
        dialog.addButton("ไว้ทีหลัง", QMessageBox.RejectRole)
        dialog.setDefaultButton(install)
        dialog.exec()
        if dialog.clickedButton() is install:
            destination = Path(tempfile.gettempdir()) / f"NovelDownloader-Setup-{update.version}.exe"
            self._download_update(update, destination)

    def _download_update(self, update: UpdateInfo, destination: Path):
        dialog = QProgressDialog("กำลังดาวน์โหลดและตรวจสอบไฟล์ติดตั้ง…", "ยกเลิก", 0, 100, self)
        dialog.setWindowTitle(f"ดาวน์โหลด v{update.version}")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        worker = _UpdateDownloadWorker(update, destination, self)
        self._update_download_worker = worker
        self._update_progress = dialog
        dialog.canceled.connect(worker.requestInterruption)
        worker.progress.connect(dialog.setValue)

        def complete(path, error):
            self._update_download_worker = None
            self._update_progress = None
            dialog.close()
            dialog.deleteLater()
            if error:
                QMessageBox.warning(self, "ดาวน์โหลดอัปเดตไม่ได้", error)
                return
            try:
                subprocess.Popen([str(path)], close_fds=True)
                QApplication.quit()
            except OSError as exc:
                QMessageBox.warning(self, "เปิดตัวติดตั้งไม่ได้", str(exc))

        worker.finished_download.connect(complete)
        worker.start()

    def closeEvent(self, event):
        workers = [self.add_worker, self.panel.worker, self._update_check_worker, self._update_download_worker]
        running = [worker for worker in workers if worker and worker.isRunning()]
        if running:
            QMessageBox.information(self, "กำลังทำงาน", "รอให้การตรวจหรือดาวน์โหลดเสร็จก่อนปิดโปรแกรม")
            event.ignore()
            return
        event.accept()
