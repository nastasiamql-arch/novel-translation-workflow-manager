"""Independent Novel Downloader page; no NovelProfile or translation workflow access."""
from pathlib import Path
from threading import Event

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from ..downloader.registry import SourceRegistry
from ..downloader.sources.tomatomtl_browser import TomatoMTLBrowserSource
from ..downloader.standalone_service import StandaloneDownloadService
from ..downloader.standalone_storage import DownloaderRepository
from ..downloader.worker import DownloaderWorker


class StandaloneDownloaderPage(QWidget):
    """Downloader owns its books, jobs and outputs; only the UI shell is shared."""

    login_browser_ready = Signal()
    login_more_time = Signal(str)

    def __init__(self, owner):
        super().__init__(owner)
        self.store = DownloaderRepository(owner.repo.root / "downloader")
        current = SourceRegistry.builtins(self.store.root / "sources")
        adapters = [TomatoMTLBrowserSource(self.store.root / "browser_profile")]
        adapters.extend(source for source in current.list_sources() if source.id != "tomatomtl")
        self.registry = SourceRegistry(adapters)
        self.service = StandaloneDownloadService(self.store, self.registry)
        self.worker = None
        self.book_id = None
        self.pending = ""
        self._chapters = []
        self._login_confirmed = None
        self.login_browser_ready.connect(self.on_login_browser_ready)
        self.login_more_time.connect(self.on_login_more_time)
        root = QVBoxLayout(self)
        title = QLabel("Novel Downloader · Chinese Raw")
        title.setObjectName("sectionHeading")
        root.addWidget(title)
        note = QLabel("Chrome/Edge ของ Downloader ใช้โปรไฟล์แยกและจำ Session ไว้ "
                      "จนกว่าเว็บจะให้เข้าสู่ระบบอีกครั้ง · หากใช้ครั้งแรก "
                      "ให้กด 'เข้าสู่ระบบ Chrome' ก่อนตรวจรายการตอน")
        note.setWordWrap(True)
        root.addWidget(note)

        form = QFormLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://tomatomtl.com/book/...")
        self.url.textEdited.connect(self._invalidate)
        form.addRow("URL นิยาย", self.url)
        location = QHBoxLayout()
        self.destination = QLineEdit(str(Path.home() / "Documents" / "NovelDownloads"))
        choose = QPushButton("เลือกโฟลเดอร์")
        choose.clicked.connect(self.choose_folder)
        location.addWidget(self.destination, 1)
        location.addWidget(choose)
        form.addRow("โฟลเดอร์บันทึก", location)
        chapters = QHBoxLayout()
        self.start = QSpinBox()
        self.end = QSpinBox()
        for field in (self.start, self.end):
            field.setRange(1, 999999)
        self.end.setValue(10)
        chapters.addWidget(self.start)
        chapters.addWidget(QLabel("ถึง"))
        chapters.addWidget(self.end)
        form.addRow("ช่วงตอน", chapters)
        self.mode = QComboBox()
        self.mode.addItem("C · แยกตอนและรวมไฟล์", "both")
        self.mode.addItem("A · แยกไฟล์รายตอน", "separate")
        self.mode.addItem("B · รวมไฟล์เดียว", "combined")
        form.addRow("รูปแบบ TXT", self.mode)
        self.digits = QSpinBox()
        self.digits.setRange(1, 8)
        self.digits.setValue(4)
        form.addRow("จำนวนหลักชื่อไฟล์", self.digits)
        self.delay = QSpinBox()
        self.delay.setRange(10, 3600)
        self.delay.setSuffix(" วินาที")
        self.delay.setValue(10)
        form.addRow("หน่วงขั้นต่ำระหว่างบท", self.delay)
        root.addLayout(form)

        self.with_title = QCheckBox("เพิ่มชื่อตอนในชื่อไฟล์")
        self.permission = QCheckBox("ยืนยันว่ามีสิทธิ์เก็บเนื้อหาและเว็บไซต์อนุญาตให้ดาวน์โหลดอัตโนมัติ")
        self.permission.setObjectName("downloaderPermission")
        root.addWidget(self.with_title)
        root.addWidget(self.permission)
        self.summary = QLabel("ตรวจสอบ URL ก่อนเริ่มงาน · โหลดทีละบทและหยุดเมื่อเว็บไซต์จำกัดการเข้าถึง")
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        browser_actions = QHBoxLayout()
        self.login_button = QPushButton("เข้าสู่ระบบ Chrome Downloader")
        self.login_button.clicked.connect(self.open_login)
        self.login_done_button = QPushButton("เข้าสู่ระบบเสร็จแล้ว")
        self.login_done_button.clicked.connect(self.confirm_login)
        self.login_done_button.setEnabled(False)
        self.login_done_button.setVisible(False)
        browser_actions.addWidget(self.login_button)
        browser_actions.addWidget(self.login_done_button)
        root.addLayout(browser_actions)
        buttons = QHBoxLayout()
        self.inspect_button = QPushButton("ตรวจสอบรายการตอน")
        self.inspect_button.clicked.connect(self.inspect)
        self.download_button = QPushButton("เริ่มดาวน์โหลด")
        self.download_button.clicked.connect(self.download)
        self.download_button.setEnabled(False)
        self.pause_button = QPushButton("หยุดชั่วคราว")
        self.pause_button.clicked.connect(self.pause)
        self.pause_button.setEnabled(False)
        self.open_button = QPushButton("เปิดหน้าเว็บ")
        self.open_button.clicked.connect(self.open_website)
        for item in (self.inspect_button, self.download_button, self.pause_button, self.open_button):
            buttons.addWidget(item)
        root.addLayout(buttons)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)
        self.book_list = QListWidget()
        self.book_list.setMaximumHeight(110)
        self.book_list.itemClicked.connect(self.select_book)
        root.addWidget(QLabel("นิยายที่เคยตรวจสอบ"))
        root.addWidget(self.book_list)
        self.refresh_books()
        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(self.stop_worker)

    def _invalidate(self, _text):
        self.book_id = None
        self.download_button.setEnabled(False)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์สำหรับ TXT", self.destination.text())
        if folder:
            self.destination.setText(folder)

    def refresh_books(self):
        self.book_list.clear()
        for item in self.store.list_books():
            from PySide6.QtWidgets import QListWidgetItem
            row = QListWidgetItem(item["title"] + " · " + item["source_id"])
            row.setData(0x0100, item["id"])
            self.book_list.addItem(row)

    def select_book(self, selected):
        entry = self.store.get_book(selected.data(0x0100))
        self.url.setText(entry["url"])
        self.destination.setText(entry["output_dir"])
        self.book_id = entry["id"]
        self.mode.setCurrentIndex({"both": 0, "separate": 1, "combined": 2}.get(entry["mode"], 0))
        self.digits.setValue(entry["digits"])
        self.with_title.setChecked(entry.get("include_title", False))
        self.download_button.setEnabled(True)
        self.summary.setText("เลือกนิยายที่บันทึกไว้ · ตรวจสอบรายการอีกครั้งก่อนเริ่ม")

    def open_website(self):
        value = self.url.text().strip()
        try:
            self.registry.match(value)
        except ValueError:
            QMessageBox.warning(self, "URL", "URL ต้องเป็นเว็บไซต์ Source ที่รองรับ")
            return
        QDesktopServices.openUrl(QUrl(value))

    def _start(self, purpose, operation):
        if self.worker and self.worker.isRunning():
            return
        self.pending = purpose
        self.inspect_button.setEnabled(False)
        self.download_button.setEnabled(False)
        self.login_button.setEnabled(False)
        self.pause_button.setEnabled(True)
        self.pause_button.setText("ยกเลิกเข้าสู่ระบบ" if purpose == "login" else "หยุดชั่วคราว")
        self.worker = DownloaderWorker(operation, self)
        self.worker.progress.connect(self.on_progress)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.cancelled.connect(self.on_paused)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def open_login(self):
        if self.worker and self.worker.isRunning():
            return
        self._login_confirmed = Event()
        self.login_done_button.setVisible(True)
        self.login_done_button.setEnabled(False)
        source = self.registry.get("tomatomtl")
        confirmation = self._login_confirmed
        self.summary.setText("กำลังเปิด Chrome/Edge เฉพาะ Downloader... "
                             "ระบบจะรอคุณ Login โดยไม่กำหนดเวลาหมดอายุ")
        self._start("login", lambda cancel, progress: source.prepare_login(
            confirmed=confirmation, cancel=cancel,
            on_ready=self.login_browser_ready.emit,
            on_waiting=lambda message: self.login_more_time.emit(message)))

    def on_login_browser_ready(self):
        self.login_done_button.setVisible(True)
        self.login_done_button.setEnabled(True)
        self.summary.setText("Chrome/Edge เปิดแล้ว: เข้าสู่ระบบ TomatoMTL "
                             "ในหน้าต่างนั้นให้เสร็จก่อน แล้วกด 'เข้าสู่ระบบเสร็จแล้ว' "
                             "ไม่จำกัดเวลาในการกรอกรหัสผ่าน")

    def confirm_login(self):
        if self.pending != "login" or self._login_confirmed is None:
            return
        self.login_done_button.setEnabled(False)
        self.summary.setText("กำลังตรวจว่า Chrome Downloader เข้าสู่ระบบแล้ว...")
        self._login_confirmed.set()

    def on_login_more_time(self, message):
        self.summary.setText(message)
        self.login_done_button.setEnabled(True)

    def inspect(self):
        url = self.url.text().strip()
        try:
            self.registry.match(url)
        except ValueError as exc:
            QMessageBox.warning(self, "URL", str(exc))
            return
        self.summary.setText("กำลังเปิด Chrome/Edge และตรวจสอบรายการตอนในหน้าเว็บ...")
        self._start("inspect", lambda cancel, progress: self.service.inspect(url))

    def download(self):
        if not self.book_id:
            return
        if not self.permission.isChecked():
            QMessageBox.warning(self, "สิทธิ์การใช้งาน", "โปรดยืนยันสิทธิ์และข้อตกลงการดาวน์โหลดก่อน")
            return
        entry = self.store.get_book(self.book_id)
        if Path(self.destination.text()).expanduser().resolve() != Path(entry["output_dir"]):
            QMessageBox.warning(self, "โฟลเดอร์", "เปลี่ยนโฟลเดอร์แล้ว กรุณาตรวจสอบ URL อีกครั้ง")
            return
        self.store.save_book(
            type("Book", (), {"source_id": entry["source_id"], "book_id": entry["book_id"],
                               "url": entry["url"], "title": entry["title"]})(),
            self.destination.text(), mode=self.mode.currentData(),
            digits=self.digits.value(), include_title=self.with_title.isChecked()
        )
        # Capture widget values on the UI thread; a QThread must not read Qt widgets.
        job = {"book_id": self.book_id, "start": self.start.value(),
               "end": self.end.value(), "mode": self.mode.currentData(),
               "digits": self.digits.value(), "include_title": self.with_title.isChecked(),
               "delay": self.delay.value()}
        self.progress_bar.setValue(0)
        self._start("download", lambda cancel, progress: self.service.download_range(
            job["book_id"], job["start"], job["end"], mode=job["mode"],
            digits=job["digits"], include_title=job["include_title"], delay=job["delay"],
            cancel=cancel, progress=progress))
        self.summary.setText("เริ่มงาน · ตรวจสอบแต่ละบทก่อนบันทึก TXT")

    def pause(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.summary.setText("กำลังหยุดอย่างปลอดภัยหลังคำขอปัจจุบัน...")

    def on_progress(self, position, total, title, downloaded, skipped, failed):
        self.progress_bar.setValue(round(100 * position / total) if total else 0)
        self.summary.setText(
            f"{position}/{total} · รับใหม่ {downloaded} · ใช้ Cache {skipped} · ล้มเหลว {failed} · {title}"
        )

    def on_completed(self, result):
        if self.pending == "login":
            self.summary.setText("เข้าสู่ระบบเรียบร้อย · บันทึก Session ในโปรไฟล์ Chrome "
                                 "ของ Downloader แล้ว · ครั้งถัดไปใช้ Session เดิมได้")
        elif self.pending == "inspect":
            book, chapters = result
            try:
                entry = self.store.save_book(book, self.destination.text(),
                                             mode=self.mode.currentData(), digits=self.digits.value(),
                                             include_title=self.with_title.isChecked())
            except Exception as exc:
                self.on_failed(str(exc))
                return
            self.book_id = entry["id"]
            self._chapters = chapters
            self.end.setValue(max(1, len(chapters)))
            self.summary.setText(f"ตรวจสอบได้ {len(chapters)} ตอน · {book.title} · พร้อมเลือกช่วง")
            self.refresh_books()
        else:
            self.summary.setText(
                f"เสร็จสิ้น · รับใหม่ {result.downloaded} · Cache {result.skipped} · ผิดพลาด {result.failed}"
            )
            if result.errors:
                QMessageBox.warning(self, "ผลการดาวน์โหลด", "\n".join(result.errors[:12]))

    def on_failed(self, message):
        self.summary.setText("งานไม่สำเร็จ · " + str(message))
        QMessageBox.warning(self, "Novel Downloader", str(message))

    def on_paused(self):
        self.summary.setText("หยุดแล้ว · สั่งเริ่มอีกครั้งเพื่อทำต่อจาก Manifest")

    def on_finished(self):
        self.inspect_button.setEnabled(True)
        self.download_button.setEnabled(bool(self.book_id))
        self.login_button.setEnabled(True)
        self.login_done_button.setEnabled(False)
        self.login_done_button.setVisible(False)
        self._login_confirmed = None
        self.pause_button.setEnabled(False)
        self.pause_button.setText("หยุดชั่วคราว")
        worker, self.worker = self.worker, None
        if worker:
            worker.deleteLater()

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(30000)
