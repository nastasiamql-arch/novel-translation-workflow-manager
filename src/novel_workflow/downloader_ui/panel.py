from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox, QVBoxLayout,
                               QWidget)

from ..downloader.worker import DownloaderWorker
from .source_manager import SourceManagerDialog


class DownloaderBookPanel(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.book = None
        self.worker = None
        self._pending = ""

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignTop)
        self.heading = QLabel("เริ่มต้นดาวน์โหลด")
        self.heading.setObjectName("pageTitle")
        layout.addWidget(self.heading)

        metadata = QGroupBox("ข้อมูลเรื่อง")
        form = QFormLayout(metadata)
        self.source_value = QLabel("—")
        self.author_value = QLabel("—")
        self.url_value = QLabel("—")
        self.url_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.output_value = QLabel("ยังไม่ได้กำหนด")
        self.output_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Source", self.source_value)
        form.addRow("ผู้เขียน", self.author_value)
        form.addRow("URL", self.url_value)
        form.addRow("โฟลเดอร์จัดเก็บ", self.output_value)
        layout.addWidget(metadata)

        actions = QHBoxLayout()
        self.output_button = QPushButton("เปลี่ยนโฟลเดอร์เรื่องนี้")
        self.output_button.clicked.connect(self.choose_output_folder)
        self.manager_button = QPushButton("จัดการ Sources")
        self.manager_button.clicked.connect(self.open_source_manager)
        actions.addWidget(self.output_button)
        actions.addWidget(self.manager_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        download_group = QGroupBox("ดาวน์โหลดต้นฉบับ")
        download_layout = QVBoxLayout(download_group)
        self.summary = QLabel(
            "1. กด + เพิ่มจาก URL ที่มุมขวาบน\n"
            "2. เลือกนิยายจากรายการทางซ้าย\n"
            "3. กด ตรวจตอนล่าสุด แล้วเลือก ดาวน์โหลดตอนใหม่"
        )
        self.summary.setWordWrap(True)
        download_layout.addWidget(self.summary)
        download_actions = QHBoxLayout()
        self.check_button = QPushButton("ตรวจตอนล่าสุด")
        self.check_button.clicked.connect(self.check)
        self.new_button = QPushButton("ดาวน์โหลดตอนใหม่")
        self.new_button.clicked.connect(self.download_new)
        self.range_button = QPushButton("ดาวน์โหลดช่วงตอน")
        self.range_button.clicked.connect(self.download_range)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.check_button, self.new_button, self.range_button, self.cancel_button):
            download_actions.addWidget(button)
        download_layout.addLayout(download_actions)

        range_form = QHBoxLayout()
        self.start = QSpinBox(); self.start.setRange(1, 999999)
        self.end = QSpinBox(); self.end.setRange(1, 999999)
        range_form.addWidget(QLabel("เริ่มตอน")); range_form.addWidget(self.start)
        range_form.addWidget(QLabel("ถึง")); range_form.addWidget(self.end)
        self.skip_existing = QCheckBox("ข้ามไฟล์ที่มีอยู่แล้ว")
        self.skip_existing.setChecked(True)
        range_form.addWidget(self.skip_existing)
        self.overwrite_selected = QCheckBox("เขียนทับในช่วงที่เลือก")
        range_form.addWidget(self.overwrite_selected)
        range_form.addStretch(1)
        download_layout.addLayout(range_form)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        download_layout.addWidget(self.progress)
        self.chapter_list = QListWidget()
        download_layout.addWidget(self.chapter_list, 1)
        layout.addWidget(download_group, 1)
        self.set_book(None)

    def set_book(self, book):
        self.book = book
        binding = book.source_binding if book else None
        self.heading.setText(book.title if book else "เริ่มต้นดาวน์โหลด")
        self.source_value.setText(binding.source_id if binding else "ยังไม่ผูกแหล่ง")
        self.author_value.setText(book.author or "—" if book else "—")
        self.url_value.setText(binding.book_url if binding else "—")
        self.output_value.setText(book.output_dir if book and book.output_dir else "ยังไม่ได้กำหนด")
        if binding:
            self.summary.setText(
                f"จำ URL แล้ว · ล่าสุด {binding.last_downloaded_chapter} จาก "
                f"{binding.last_known_chapter_count} ตอน · Chinese Raw / 原文"
            )
            self.end.setValue(max(1, binding.last_known_chapter_count))
        else:
            self.summary.setText(
                "1. กด + เพิ่มจาก URL ที่มุมขวาบน\n"
                "2. เลือกนิยายจากรายการทางซ้าย\n"
                "3. กด ตรวจตอนล่าสุด แล้วเลือก ดาวน์โหลดตอนใหม่"
            )
        self.chapter_list.clear()
        self._busy(False)

    def open_source_manager(self):
        dialog = SourceManagerDialog(self.owner.repository.sources_dir, self)
        dialog.sources_changed.connect(self.owner.reload_sources)
        dialog.exec()

    def choose_output_folder(self):
        if not self.book:
            return
        current = str(Path(self.book.output_dir).parent) if self.book.output_dir else ""
        selected = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์จัดเก็บนิยาย", current)
        if not selected:
            return
        target = Path(selected) / self.owner.repository.novel_folder_name(self.book.title)
        self.book.output_dir = str(target)
        self.owner.repository.save_book(self.book)
        self.set_book(self.book)

    def _busy(self, busy):
        has_binding = bool(self.book and self.book.source_binding)
        self.output_button.setEnabled(not busy and bool(self.book))
        self.manager_button.setEnabled(not busy)
        self.check_button.setEnabled(not busy and has_binding)
        self.new_button.setEnabled(not busy and has_binding)
        self.range_button.setEnabled(not busy and has_binding)
        self.cancel_button.setEnabled(busy)

    def _start(self, operation, pending):
        if not self.book or self.worker and self.worker.isRunning():
            return
        self._pending = pending
        self._busy(True)
        self.chapter_list.clear()
        self.worker = DownloaderWorker(operation, self)
        self.worker.progress.connect(self._progress)
        self.worker.completed.connect(self._completed)
        self.worker.failed.connect(self._failed)
        self.worker.cancelled.connect(self._cancelled)
        self.worker.finished.connect(lambda: self._busy(False))
        self.worker.start()

    def check(self):
        self._start(lambda cancel, progress: self.owner.service.check_updates(self.book), "check")

    def download_new(self):
        self._start(lambda cancel, progress: self.owner.service.download_updates(
            self.book, skip_existing=self.skip_existing.isChecked(), cancel=cancel, progress=progress), "download")

    def download_range(self):
        start, end = self.start.value(), self.end.value()
        overwrite = self.overwrite_selected.isChecked()
        self._start(lambda cancel, progress: self.owner.service.download_range(
            self.book, start, end, skip_existing=self.skip_existing.isChecked() and not overwrite,
            overwrite=overwrite, cancel=cancel, progress=progress), "download")

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()

    def _progress(self, current, total, title, downloaded, skipped, failed):
        self.progress.setValue(round(current * 100 / total) if total else 0)
        self.summary.setText(f"{current}/{total} · โหลด {downloaded} · ข้าม {skipped} · ผิดพลาด {failed} · {title}")

    def _completed(self, result):
        self.owner.refresh_books(self.book.id)
        self.book = self.owner.repository.get_book(self.book.id)
        if self._pending == "check":
            self.summary.setText(
                f"บนเว็บ {len(result['chapters'])} ตอน · ดาวน์โหลดแล้ว {result['downloaded']} · "
                f"พบตอนใหม่ {len(result['missing'])}"
            )
            for chapter in result["missing"]:
                self.chapter_list.addItem(f"{chapter.index:04d} {chapter.title}")
            if result["warnings"]:
                QMessageBox.warning(self, "แคตตาล็อกเปลี่ยนแปลง",
                                    "ตรวจพบการเปลี่ยนลำดับตอน:\n" + "\n".join(result["warnings"][:12]))
        else:
            blocked = any("anti-bot challenge" in error.casefold() for error in result.errors)
            limited = any("rate limit" in error.casefold() for error in result.errors)
            if blocked:
                self.summary.setText(
                    f"เว็บไซต์ขอให้หยุด · โหลด {result.downloaded} · ข้าม {result.skipped} · "
                    "เปิดเว็บแล้วลองใหม่ภายหลังได้"
                )
            elif limited:
                self.summary.setText(
                    f"เว็บไซต์จำกัดความถี่ · โหลด {result.downloaded} · ข้าม {result.skipped} · "
                    "รอสักครู่แล้วเริ่มใหม่เพื่อทำต่อ"
                )
            else:
                self.summary.setText(f"เสร็จแล้ว · โหลด {result.downloaded} · ข้าม {result.skipped} · ผิดพลาด {result.failed}")
            if result.errors:
                dialog = QMessageBox(self)
                dialog.setIcon(QMessageBox.Warning)
                dialog.setWindowTitle("หยุดดาวน์โหลดตามคำขอของเว็บไซต์" if blocked or limited else "บางตอนไม่สำเร็จ")
                dialog.setText("\n".join(result.errors[:10]))
                open_button = None
                if blocked and self.book and self.book.source_binding:
                    open_button = dialog.addButton("เปิดหน้าเว็บใน Browser", QMessageBox.AcceptRole)
                dialog.addButton(QMessageBox.Ok)
                dialog.exec()
                if dialog.clickedButton() is open_button and open_button is not None:
                    QDesktopServices.openUrl(QUrl(self.book.source_binding.book_url))

    def _failed(self, message):
        if "anti-bot challenge" not in message.casefold() or not self.book or not self.book.source_binding:
            QMessageBox.warning(self, "ดาวน์โหลดไม่สำเร็จ", message)
            return
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("เว็บขอให้ยืนยันว่าเป็นผู้ใช้")
        dialog.setText(message)
        open_button = dialog.addButton("เปิดหน้าเว็บใน Browser", QMessageBox.AcceptRole)
        dialog.addButton(QMessageBox.Ok)
        dialog.exec()
        if dialog.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(self.book.source_binding.book_url))

    def _cancelled(self):
        self.summary.setText("ยกเลิกแล้ว · เปิดเรื่องนี้อีกครั้งเพื่อทำต่อจาก manifest")
