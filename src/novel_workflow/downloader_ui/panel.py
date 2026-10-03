from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QProgressBar, QMessageBox, QCheckBox, QListWidget,
                               QListWidgetItem, QGroupBox, QFormLayout)

from ..storage import data_root
from ..downloader.registry import SourceRegistry
from ..downloader.service import DownloadService
from ..downloader.worker import DownloaderWorker
from .source_manager import SourceManagerDialog


class DownloaderPage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.profile = owner.profile
        self.source_dir = data_root() / "sources"
        self.registry = SourceRegistry.builtins(self.source_dir)
        self.service = DownloadService(owner.repo, self.registry)
        self.worker = None
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        heading = QLabel("ต้นฉบับเว็บ")
        heading.setObjectName("currentNovel")
        layout.addWidget(heading)
        form = QFormLayout()
        row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://tomatomtl.com/book/...")
        row.addWidget(self.url, 1)
        self.inspect_button = QPushButton("ตรวจสอบและผูก")
        self.inspect_button.clicked.connect(self.inspect)
        row.addWidget(self.inspect_button)
        self.create_button = QPushButton("สร้างโปรไฟล์จาก URL")
        self.create_button.clicked.connect(self.create_profile_from_url)
        row.addWidget(self.create_button)
        form.addRow("URL", row)
        self.source_value = QLabel("ยังไม่เชื่อมต่อ")
        form.addRow("Source", self.source_value)
        self.title_value = QLabel("—")
        form.addRow("ชื่อเรื่อง", self.title_value)
        self.book_id_value = QLabel("—")
        form.addRow("Book ID", self.book_id_value)
        self.mode_value = QLabel("Chinese Raw / 原文")
        form.addRow("ภาษา", self.mode_value)
        layout.addLayout(form)
        self.summary = QLabel("เชื่อม URL เพื่อดูจำนวนตอนและดาวน์โหลดต้นฉบับ")
        layout.addWidget(self.summary)
        actions = QHBoxLayout()
        self.check_button = QPushButton("เช็กต้นฉบับ")
        self.check_button.clicked.connect(self.check)
        self.new_button = QPushButton("ดาวน์โหลดตอนใหม่")
        self.new_button.clicked.connect(self.download_new)
        self.range_button = QPushButton("ดาวน์โหลดช่วงตอน")
        self.range_button.clicked.connect(self.download_range)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.clicked.connect(self.cancel)
        self.manager_button = QPushButton("จัดการ Sources")
        self.manager_button.clicked.connect(self.open_source_manager)
        for button in (self.check_button, self.new_button, self.range_button, self.cancel_button, self.manager_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.skip_existing = QCheckBox("ข้ามตอนที่มีอยู่แล้ว")
        self.skip_existing.setChecked(True)
        layout.addWidget(self.skip_existing)
        self.overwrite_selected = QCheckBox("เขียนทับไฟล์ในช่วงตอนที่เลือก")
        layout.addWidget(self.overwrite_selected)
        range_form = QHBoxLayout()
        self.start = QSpinBox(); self.start.setMinimum(1); self.start.setMaximum(999999)
        self.end = QSpinBox(); self.end.setMinimum(1); self.end.setMaximum(999999)
        range_form.addWidget(QLabel("เริ่มตอน")); range_form.addWidget(self.start)
        range_form.addWidget(QLabel("ถึง")); range_form.addWidget(self.end)
        range_form.addStretch(1)
        layout.addLayout(range_form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.chapter_list = QListWidget()
        layout.addWidget(self.chapter_list, 1)
        self._load_binding()
        self._busy(False)

    def _load_binding(self):
        binding = self.profile.source_binding
        if binding:
            self.url.setText(binding.book_url)
            self.source_value.setText(binding.source_id)
            self.book_id_value.setText(binding.remote_book_id)
            self.mode_value.setText("Chinese Raw / 原文" if binding.content_mode == "raw_zh" else binding.content_mode)
            self.summary.setText(f"จำ URL นี้ไว้แล้ว · ดาวน์โหลดล่าสุดถึงตอน {binding.last_downloaded_chapter} จาก {binding.last_known_chapter_count}")

    def open_source_manager(self):
        dialog = SourceManagerDialog(self)
        dialog.sources_changed.connect(self.reload_sources)
        dialog.exec()

    def reload_sources(self):
        self.registry = SourceRegistry.builtins(self.source_dir)
        self.service = DownloadService(self.owner.repo, self.registry)

    def _busy(self, busy):
        self.inspect_button.setEnabled(not busy)
        self.create_button.setEnabled(not busy)
        self.check_button.setEnabled(not busy and bool(self.profile.source_binding))
        self.new_button.setEnabled(not busy and bool(self.profile.source_binding))
        self.range_button.setEnabled(not busy and bool(self.profile.source_binding))
        self.cancel_button.setEnabled(busy)

    def _start(self, operation):
        if self.worker and self.worker.isRunning(): return
        self._busy(True)
        self.chapter_list.clear()
        self.worker = DownloaderWorker(operation, self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def inspect(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.information(self, "ใส่ URL", "กรอก URL หนังสือต้นฉบับก่อน")
            return
        self._start(lambda cancel, progress: self.service.inspect_book(url))
        self._pending = "inspect"

    def create_profile_from_url(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.information(self, "ใส่ URL", "กรอก URL หนังสือต้นฉบับก่อน")
            return
        self._start(lambda cancel, progress: self.service.inspect_book(url))
        self._pending = "create"

    def check(self):
        self._start(lambda cancel, progress: self.service.check_updates(self.profile))
        self._pending = "check"

    def download_new(self):
        self._start(lambda cancel, progress: self.service.download_updates(
            self.profile, skip_existing=self.skip_existing.isChecked(), cancel=cancel, progress=progress))
        self._pending = "download"

    def download_range(self):
        start, end = self.start.value(), self.end.value()
        overwrite = self.overwrite_selected.isChecked()
        self._start(lambda cancel, progress: self.service.download_range(
            self.profile, start, end, skip_existing=self.skip_existing.isChecked() and not overwrite,
            overwrite=overwrite, cancel=cancel, progress=progress))
        self._pending = "download"

    def cancel(self):
        if self.worker and self.worker.isRunning(): self.worker.requestInterruption()

    def _progress(self, current, total, title, downloaded, skipped, failed):
        self.progress.setValue(round(current * 100 / total) if total else 0)
        self.summary.setText(f"{current}/{total} · โหลด {downloaded} · ข้าม {skipped} · ผิดพลาด {failed} · {title}")

    def _completed(self, result):
        if self._pending in {"inspect", "create"}:
            source, book = result
            current = self.profile.source_binding
            source_folder = self.owner.repo.profile_dir(self.profile.id) / "source"
            if self._pending == "inspect" and current and any(source_folder.glob("*")):
                answer = QMessageBox.question(self, "เปลี่ยนแหล่งต้นฉบับ?", "โปรไฟล์นี้มีไฟล์ต้นฉบับอยู่แล้ว การเปลี่ยนแหล่งจะผูก manifest กับหนังสือใหม่ ต้องการดำเนินการต่อหรือไม่?")
                if answer != QMessageBox.Yes: return
            if self._pending == "create":
                from ..services import ProfileService
                self.profile = ProfileService(self.owner.repo).create(book.title)
                self.owner.refresh_profiles(self.profile.id)
            self.service.bind(self.profile, book.url, book, source)
            self.owner.profile = self.profile
            self.source_value.setText(source.name)
            self.title_value.setText(book.title)
            self.book_id_value.setText(book.book_id)
            self.summary.setText(f"{book.total_chapters} ตอนบนเว็บ · ผูกกับโปรไฟล์แล้ว")
            self._load_binding()
            if self._pending == "create":
                self.owner.open_downloader()
        elif self._pending == "check":
            self.title_value.setText(result["book"].title)
            self.book_id_value.setText(result["book"].book_id)
            self.summary.setText(f"บนเว็บ {len(result['chapters'])} ตอน · ในเครื่อง {result['downloaded']} · พบตอนใหม่ {len(result['missing'])}")
            for chapter in result["missing"]:
                self.chapter_list.addItem(f"{chapter.index:04d} {chapter.title}")
            if result["warnings"]:
                QMessageBox.warning(self, "แคตตาล็อกเปลี่ยนแปลง", "ตรวจพบการเปลี่ยนลำดับตอน:\n" + "\n".join(result["warnings"][:12]))
        else:
            self.summary.setText(f"เสร็จแล้ว · โหลด {result.downloaded} · ข้าม {result.skipped} · ผิดพลาด {result.failed}")
            if result.errors:
                QMessageBox.warning(self, "บางตอนไม่สำเร็จ", "\n".join(result.errors[:10]))

    def _failed(self, message):
        QMessageBox.warning(self, "ดาวน์โหลดไม่สำเร็จ", message)

    def _cancelled(self):
        self.summary.setText("ยกเลิกแล้ว · เปิดหน้านี้อีกครั้งเพื่อดาวน์โหลดต่อจาก manifest")
