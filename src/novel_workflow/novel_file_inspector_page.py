"""Dedicated full-page inspector; intentionally independent from workflow stages."""
from __future__ import annotations

from pathlib import Path
import json
import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTableView, QVBoxLayout, QHeaderView, QMenu,
    QWidget, QDialog, QTableWidget, QTableWidgetItem, QTabWidget,
)

from .novel_file_inspector import Inspection, inspect, read_source, decode_text, read_combined_chapter
from .novel_file_inspector_history import InspectorStore
from .novel_file_inspector_renumber import (
    plan_renumber, plan_heading_repair, execute_new, execute_in_place, restore_backup,
)


class ScanWorker(QThread):
    progress = Signal(int, int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, source, kind, minimum, reviews, options, cache):
        super().__init__()
        self.source, self.kind, self.minimum = source, kind, minimum
        self.reviews, self.options, self.cache = reviews, options, cache
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def requestInterruption(self):
        self.cancel()
        super().requestInterruption()

    def run(self):
        try:
            result = inspect(self.source, self.kind, self.minimum,
                             lambda pos, total: self.progress.emit(pos, total),
                             self._cancel.is_set, self.reviews, self.options, self.cache)
            self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class WriteWorker(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, plan, destination, in_place, backup_root):
        super().__init__()
        self.plan, self.destination, self.in_place, self.backup_root = plan, destination, in_place, backup_root

    def run(self):
        try:
            value = (execute_in_place(self.plan, self.backup_root) if self.in_place
                     else execute_new(self.plan, self.destination))
            self.completed.emit(value)
        except Exception as exc:
            self.failed.emit(str(exc))


class FileTable(QAbstractTableModel):
    HEADERS = ("บท", "ชื่อไฟล์", "ตัวอักษร", "สถานะ")

    def __init__(self):
        super().__init__()
        self.rows = []
        self.combined = False

    def reset_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return ("บท", "หัวบท / เล่ม", "ตัวอักษร", "สถานะ")[section] if self.combined else self.HEADERS[section]
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        if role == Qt.UserRole:
            return row.chapter if index.column() == 0 else row.name
        if role == Qt.DisplayRole:
            c = index.column()
            values = [f"{row.chapter:04d}" if row.chapter is not None else "—",
                      row.name, "—" if row.virtual else f"{row.count:,}",
                      (f"หัวบท {row.heading} ≠ {row.chapter}" if row.heading is not None and row.chapter is not None and row.heading != row.chapter else row.error or ", ".join(row.reasons) or "ปกติ") + (f" · ซ้ำกับ {row.duplicate_of}" if row.duplicate_of else "") + (" · ยืนยันเก็บไว้" if row.review == "keep" and not row.review_stale else "")]
            return values[c]
        if role == Qt.ToolTipRole:
            return (row.error or ", ".join(row.reasons)) + (f" · ซ้ำกับ {row.duplicate_of}" if row.duplicate_of else "")
        return None


class InspectorFilter(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.category = "all"
        self.query = ""
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, row, parent):
        item = self.sourceModel().rows[row]
        if self.query and self.query not in item.name.casefold() and self.query not in str(item.chapter):
            return False
        return {"all": lambda: True, "suspicious": lambda: item.suspicious,
                "missing": lambda: item.virtual,
                "heading": lambda: not item.virtual and item.heading is not None and item.chapter != item.heading,
                "short": lambda: not item.virtual and item.count < self.minimum and not item.error,
                "duplicate": lambda: bool(item.duplicate_of or "เลขบทซ้ำ" in item.reasons)}[self.category]()

    minimum = 1500

    def lessThan(self, left, right):
        a = self.sourceModel().rows[left.row()]
        b = self.sourceModel().rows[right.row()]
        col = left.column()
        if col == 0:
            return (a.chapter is None, a.chapter or 0, a.name.casefold()) < (b.chapter is None, b.chapter or 0, b.name.casefold())
        if col == 2:
            return a.count < b.count
        return str(self.sourceModel().data(left, Qt.DisplayRole)).casefold() < str(self.sourceModel().data(right, Qt.DisplayRole)).casefold()


class NovelFileInspectorPage(QWidget):
    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self.setObjectName("novelFileInspectorPage")
        self.repo = repo
        self.store = InspectorStore(repo.root)
        self.state = self.store.settings()
        self.result = None
        self.worker = None
        self.write_worker = None
        self._post_write_output = None
        self.bulk_in_place = True
        self.source, self.kind = "", "folder"
        self.pending_source = None
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(10)
        source = QHBoxLayout()
        folder = QPushButton("เลือกโฟลเดอร์ TXT")
        folder.clicked.connect(self.choose_folder)
        source.addWidget(folder)
        combined = QPushButton("เลือก TXT รวมหลายบท")
        combined.clicked.connect(self.choose_combined)
        source.addWidget(combined)
        self.more_button = QPushButton("ตัวเลือกเพิ่มเติม")
        self.more_button.clicked.connect(self.open_more)
        source.addWidget(self.more_button)
        source.addStretch(1)
        root.addLayout(source)
        self.source_label = QLabel("ยังไม่ได้เลือกไฟล์ต้นฉบับ")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

        body = root
        opts = QHBoxLayout()
        opts.addWidget(QLabel("ขั้นต่ำ"))
        self.minimum = QSpinBox()
        self.minimum.setRange(1, 1_000_000)
        self.minimum.setValue(self.state["minimum"])
        opts.addWidget(self.minimum)
        self.checks = {}
        for key, label in (("missing", "เลขขาด"), ("numbers", "เลขซ้ำ"),
                           ("short", "ไฟล์สั้น"), ("duplicates", "เนื้อหาซ้ำ"),
                           ("size", "ขนาดผิดปกติ")):
            checkbox = QCheckBox(label)
            checkbox.setChecked(self.state.get(key, True))
            self.checks[key] = checkbox
            opts.addWidget(checkbox)
        opts.addStretch(1)
        self.settings_panel = QWidget()
        self.settings_panel.setLayout(opts)
        self.settings_panel.hide()
        body.addWidget(self.settings_panel)
        controls = QHBoxLayout()
        self.scan_button = QPushButton("ตรวจสอบไฟล์")
        self.scan_button.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_button)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        controls.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        self.progress.setObjectName("inspectorScanProgress")
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.hide()
        self.progress_status = QLabel("")
        self.progress_status.setObjectName("inspectorScanStatus")
        self.progress_status.setWordWrap(True)
        self.progress_status.hide()
        progress_area = QVBoxLayout()
        progress_area.setSpacing(3)
        progress_area.addWidget(self.progress_status)
        progress_area.addWidget(self.progress)
        controls.addLayout(progress_area, 1)
        body.addLayout(controls)
        self.scan_button.hide()
        self.summary = QLabel("เลือกโฟลเดอร์ TXT เพื่อเริ่มตรวจสอบ")
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        filters = QHBoxLayout()
        self.filter = QComboBox()
        for name, key in (("ทั้งหมด", "all"), ("น่าสงสัย", "suspicious"),
                          ("หัวบทไม่ตรง", "heading"), ("เลขบทขาด", "missing"), ("ไฟล์สั้น", "short"),
                          ("ไฟล์ซ้ำ", "duplicate")):
            self.filter.addItem(name, key)
        self.filter.currentIndexChanged.connect(self.update_filter)
        filters.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ค้นหาเลขบทหรือชื่อไฟล์")
        self.search.textChanged.connect(self.update_filter)
        filters.addWidget(self.search, 1)
        body.addLayout(filters)
        splitter = QSplitter(Qt.Horizontal)
        self.model = FileTable()
        self.proxy = InspectorFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 160)
        self.table.selectionModel().selectionChanged.connect(self.show_selected)
        splitter.addWidget(self.table)
        reader = QWidget()
        read_layout = QVBoxLayout(reader)
        self.detail = QLabel("เลือกบทเพื่ออ่านเนื้อหาฉบับเต็ม")
        self.detail.setWordWrap(True)
        read_layout.addWidget(self.detail)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlaceholderText("เนื้อหาเต็มแบบอ่านอย่างเดียว")
        read_layout.addWidget(self.text, 1)
        actions = QHBoxLayout()
        self.review_buttons = []
        for label, slot in (("ก่อนหน้า", lambda: self.navigate_row(-1)),
                            ("ถัดไป", lambda: self.navigate_row(1)),
                            ("เปรียบเทียบ", self.compare_selected),
                            ("เป็นนิยาย — เก็บไว้", lambda: self.mark_selection("keep")),
                            ("คัดออก", lambda: self.mark_selection("excluded")),
                            ("ยังไม่ตัดสินใจ", lambda: self.mark_selection("pending"))):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
            if label in ("เป็นนิยาย — เก็บไว้", "คัดออก", "ยังไม่ตัดสินใจ"):
                self.review_buttons.append(button)
        read_layout.addLayout(actions)
        splitter.addWidget(reader)
        splitter.setSizes([550, 650])
        body.addWidget(splitter, 1)


        renumber = QWidget()
        form = QVBoxLayout(renumber)
        settings = QFormLayout()
        self.start = QSpinBox()
        self.start.setRange(1, 2_147_483_647)
        self.start.setValue(1)
        settings.addRow("เริ่มเลขบทใหม่", self.start)
        self.padding = QSpinBox()
        self.padding.setRange(1, 12)
        self.padding.setValue(4)
        settings.addRow("จำนวนหลักเลขบท", self.padding)
        self.heading = QCheckBox("แก้เลขหัวบทด้วย (เฉพาะที่ตรวจพบได้แน่นอน)")
        settings.addRow("วิธีการ", self.heading)
        self.in_place = QCheckBox("แก้ไฟล์ต้นฉบับจริง (สำรองก่อนทุกครั้ง)")
        self.in_place.setChecked(True)
        self.in_place.setEnabled(False)
        settings.addRow("รูปแบบผลลัพธ์", self.in_place)
        form.addLayout(settings)
        preview_button = QPushButton("สร้าง Preview")
        preview_button.clicked.connect(self.preview)
        form.addWidget(preview_button)
        self.plan_summary = QLabel("ต้องตรวจสอบไฟล์ก่อน")
        form.addWidget(self.plan_summary)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setHorizontalHeaderLabels(["ไฟล์เดิม", "ไฟล์ใหม่", "การดำเนินการ"])
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        form.addWidget(self.preview_table, 1)
        self.apply = QPushButton("ยืนยันและจัดเลขบท")
        self.apply.setEnabled(False)
        self.apply.clicked.connect(self.execute)
        self.in_place.toggled.connect(lambda *_: self.apply.setEnabled(False))
        for changed in (self.start.valueChanged, self.padding.valueChanged, self.heading.toggled):
            changed.connect(lambda *_: self.apply.setEnabled(False))
        form.addWidget(self.apply)
        self.renumber_dialog = QDialog(self)
        self.renumber_dialog.setWindowTitle("จัดเลขบทใหม่ · Preview")
        self.renumber_dialog.resize(780, 550)
        QVBoxLayout(self.renumber_dialog).addWidget(renumber)

        history = QWidget()
        hist = QVBoxLayout(history)
        self.history_combo = QComboBox()
        hist.addWidget(self.history_combo)
        load = QPushButton("เปิดผลตรวจย้อนหลัง")
        load.clicked.connect(self.load_history)
        hist.addWidget(load)
        self.operations_combo = QComboBox()
        hist.addWidget(self.operations_combo)
        restore = QPushButton("คืนค่าจาก Backup เป็นโฟลเดอร์ใหม่")
        restore.clicked.connect(self.restore)
        hist.addWidget(restore)
        hist.addStretch(1)
        self.history_dialog = QDialog(self)
        self.history_dialog.setWindowTitle("ประวัติ / กู้คืน")
        self.history_dialog.resize(720, 400)
        QVBoxLayout(self.history_dialog).addWidget(history)
        actions = QHBoxLayout()
        self.repair_buttons = []
        for label, handler in (("แก้รายการที่เลือก", lambda: self.repair_headings(True)),
                               ("แก้เลขหัวบททั้งหมด", lambda: self.repair_headings(False)),
                               ("จัดเลขบทใหม่ทั้งหมด", self.renumber_dialog.exec)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            actions.addWidget(button)
            self.repair_buttons.append(button)
        body.addLayout(actions)
        self.refresh_history()

    def open_more(self):
        menu = QMenu(self)
        menu.addAction("เกณฑ์ตรวจ", lambda: self.settings_panel.setVisible(not self.settings_panel.isVisible()))
        menu.addAction("ประวัติ / กู้คืน", self.history_dialog.exec)
        in_place = menu.addAction("ขั้นสูง: แก้ต้นฉบับจริง")
        in_place.setCheckable(True)
        in_place.setChecked(self.bulk_in_place)
        in_place.setEnabled(False)
        menu.exec(self.more_button.mapToGlobal(self.more_button.rect().bottomLeft()))

    def repair_headings(self, selected_only=False):
        if self.result and self.result.kind == "combined":
            QMessageBox.information(self, "อ่านอย่างเดียว", "TXT รวมบทไม่รองรับการแก้ไฟล์จากหน้านี้")
            return
        if not self.result or (self.worker and self.worker.isRunning()) or (self.write_worker and self.write_worker.isRunning()):
            return
        names = {r.name for r in self.selected_files()} if selected_only else None
        if selected_only and not names:
            QMessageBox.information(self, "เลือกรายการ", "เลือกไฟล์ก่อน")
            return
        plan, blocked = plan_heading_repair(self.result, names, only_changed=True)
        eligible = [r for r in plan.files if r.before is not None and r.after is not None]
        if not eligible:
            QMessageBox.information(self, "ไม่พบรายการแก้ได้", "ไม่มีหัวบทที่แก้ได้อย่างปลอดภัย")
            return
        examples = "\\n".join(f"{r.original}: {r.before} → {r.after}" for r in eligible[:10])
        warning = max((len(run) for run in self.result.shifted_heading_runs()), default=0)
        message = (f"ยืนยันให้ใช้เลขจากชื่อไฟล์เป็นหลัก?\\nแก้ {len(eligible)} ไฟล์ · ข้าม {len(blocked)} ไฟล์\\n"
                   + (f"พบหัวบทเหลื่อมต่อเนื่อง {warning} บท\\n" if warning else "")
                   + examples + "\\n\\nจะแก้ทับไฟล์เดิมโดยสำรองก่อนทุกครั้ง ไม่สร้างโฟลเดอร์ -inspected")
        if QMessageBox.question(self, "ตัวอย่างก่อนแก้", message,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        if self.bulk_in_place:
            if plan.kind != "folder":
                QMessageBox.warning(self, "รูปแบบไม่รองรับ", "แก้ต้นฉบับจริงรองรับเฉพาะโฟลเดอร์")
                return
            if QMessageBox.warning(self, "ยืนยันการแก้ไฟล์ต้นฉบับ",
                                   "ระบบจะสร้าง Backup และ Transaction Journal ก่อนแก้ไฟล์จริง ยืนยันอีกครั้ง?",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return
        source = Path(plan.source)
        base = source.stem + "-inspected"
        destination = source.with_name(base)
        index = 2
        while destination.exists():
            destination = source.with_name(f"{base}-{index}")
            index += 1
        self.plan = plan
        self.write_worker = WriteWorker(plan, None if self.bulk_in_place else str(destination),
                                        self.bulk_in_place, self.store.root / "backups")
        self.write_worker.completed.connect(self.write_done)
        self.write_worker.failed.connect(self.write_failed)
        self.write_worker.finished.connect(self.post_write_rescan)
        self.write_worker.start()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ TXT", self.source or str(Path.home()))
        if path:
            self.set_source(path, "folder")

    def choose_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "เลือก ZIP", self.source or str(Path.home()), "ZIP (*.zip)")
        if path:
            self.set_source(path, "zip")

    def choose_combined(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "เลือก TXT ที่รวมหลายบท", self.source or str(Path.home()), "TXT (*.txt)"
        )
        if path:
            self.set_source(path, "combined")

    def set_source(self, path, kind):
        if self.write_worker and self.write_worker.isRunning():
            QMessageBox.warning(self, "กำลังบันทึก", "ยังไม่สามารถเปลี่ยนโฟลเดอร์ได้")
            return
        if self.worker and self.worker.isRunning():
            self.pending_source = (str(path), kind)
            self.worker.cancel()
            return
        self.pending_source = None
        self.source, self.kind = str(path), kind
        self.source_label.setText(f"{kind.upper()}: {path}")
        self.result = None
        self.model.reset_rows([])
        self.text.clear()
        self.apply.setEnabled(False)
        self.start_scan()

    def start_scan(self):
        if self.worker and self.worker.isRunning():
            return
        if not self.source:
            QMessageBox.warning(self, "ยังไม่มีแหล่งไฟล์", "เลือกโฟลเดอร์หรือ ZIP ก่อน")
            return
        options = {key: checkbox.isChecked() for key, checkbox in self.checks.items()}
        minimum = self.minimum.value()
        self.store.save_settings({"minimum": minimum, **options})
        self.worker = ScanWorker(self.source, self.kind, minimum,
                                 self.store.reviews(self.source, self.kind), options,
                                 self.store.cache(self.source, self.kind))
        self.worker.progress.connect(self.progress_scan)
        self.worker.completed.connect(self.scan_done)
        self.worker.failed.connect(self.scan_failed)
        self.worker.finished.connect(self.finish_worker)
        self.progress.setRange(0, 0)
        self.progress_status.setText("กำลังเตรียมรายการไฟล์สำหรับตรวจสอบ…")
        self.progress_status.show()
        self.progress.show()
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker.start()

    def cancel_scan(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.progress_status.setText("กำลังยกเลิกการตรวจสอบ…")

    def progress_scan(self, n, total):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(n)
        percent = min(100, round(100 * n / total)) if total else 0
        self.progress_status.setText(
            f"กำลังตรวจไฟล์ {n:,}/{total:,} · {percent}%"
        )

    def finish_worker(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.hide()
        if self.pending_source is not None:
            path, kind = self.pending_source
            self.pending_source = None
            self.set_source(path, kind)

    def scan_failed(self, message):
        self.progress_status.setText("ตรวจสอบไม่สำเร็จ · " + message)
        QMessageBox.warning(self, "ตรวจสอบไม่สำเร็จ", message)

    def scan_done(self, result):
        if result.cancelled or self.pending_source is not None:
            self.progress_status.setText("ยกเลิกการตรวจแล้ว · ไม่มีการบันทึกผลลัพธ์บางส่วน")
            self.detail.setText("ยกเลิกการตรวจแล้ว ผลลัพธ์บางส่วนไม่ได้บันทึก")
            return
        self.progress_status.setText(
            f"ตรวจสอบเสร็จแล้ว · {result.summary()['total']:,} " +
            ("หัวบท (อ่านอย่างเดียว)" if result.kind == "combined" else "ไฟล์")
        )
        self.set_result(result)
        self.store.save_cache(result.source, result.kind, self.worker.cache)
        self.store.add_inspection(result)
        self.refresh_history()

    def set_result(self, result):
        self.result = result
        combined = result.kind == "combined"
        self.model.beginResetModel()
        self.model.combined = combined
        self.model.rows = list(result.files)
        self.model.endResetModel()
        self.table.setSortingEnabled(not combined)
        if combined:
            # Reset the proxy sort inherited from file mode; use actual chapter order.
            self.proxy.sort(-1)
        for button in self.repair_buttons + self.review_buttons:
            button.setEnabled(not combined)
        self.proxy.minimum = result.minimum
        self.proxy.invalidateFilter()
        s = result.summary()
        if combined:
            self.source_label.setText(f"TXT รวมบท (อ่านอย่างเดียว): {result.source}")
            self.summary.setText(
                f"หัวบทที่ตรวจพบ {s['total']:,} · จุดน่าสงสัย {s['suspicious']:,}"
                f" · บทสั้น {s['short']:,} · ไม่มีการแก้ต้นฉบับ"
            )
        else:
            self.summary.setText(
                f"ไฟล์ทั้งหมด {s['total']:,} · ไม่พบปัญหา {s['clean']:,} · ต้องตรวจสอบ {s['suspicious']:,} · รอตรวจทาน {s['pending_review']:,}" +
                f"  |  เลขหัวบทไม่ตรง {s['heading_mismatch']:,} · สั้นกว่าเกณฑ์ {s['short']:,} · เนื้อหาซ้ำ {s['duplicate_content']:,}" +
                f" · เลขบทขาด {s['missing']:,} · อ่านไม่ได้ {s['unreadable']:,} · แก้เลขอัตโนมัติได้ {s['repairable']:,}")
        self.preview_table.setRowCount(0)
        self.apply.setEnabled(False)
        if not combined:
            self.table.sortByColumn(0, Qt.AscendingOrder)

    def update_filter(self, *_):
        self.proxy.category = self.filter.currentData()
        self.proxy.query = self.search.text().strip().casefold()
        self.proxy.invalidateFilter()

    def selected_files(self):
        indices = self.table.selectionModel().selectedRows()
        return [self.model.rows[self.proxy.mapToSource(idx).row()] for idx in indices]

    def show_selected(self, *_):
        files = self.selected_files()
        if len(files) != 1:
            self.text.clear()
            self.detail.setText(f"เลือก {len(files)} รายการ" if files else "เลือกบทเพื่ออ่านเนื้อหา")
            return
        row = files[0]
        self.detail.setText(f"{row.name} · หัวบท {row.heading if row.heading is not None else 'ไม่พบ'} · บทจากชื่อไฟล์ {row.chapter or '—'} · {row.count:,} ตัวอักษร · {row.size/1024:.1f} KB · "
                            + (row.error or ", ".join(row.reasons) or "ไม่มีข้อสงสัย"))
        if row.virtual or row.error:
            self.text.clear()
            return
        try:
            text = (read_combined_chapter(self.result, row) if self.result.kind == "combined"
                    else decode_text(read_source(self.result.source, self.result.kind, row.name))[0])
            self.text.setPlainText(text)
        except Exception as exc:
            self.text.setPlainText(f"เปิดไฟล์ไม่ได้: {exc}")

    def navigate_row(self, delta):
        selection = self.table.selectionModel().selectedRows()
        current = selection[0].row() if selection else -1
        row = current + delta
        if 0 <= row < self.proxy.rowCount():
            self.table.selectRow(row)

    def compare_selected(self):
        files = [r for r in self.selected_files() if not r.virtual and not r.error]
        if len(files) != 2:
            QMessageBox.information(self, "เปรียบเทียบ", "เลือกไฟล์จริง 2 รายการเพื่อเปรียบเทียบ")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("เปรียบเทียบเนื้อหา")
        dialog.resize(1100, 700)
        layout = QHBoxLayout(dialog)
        for row in files:
            box = QVBoxLayout()
            box.addWidget(QLabel(row.name))
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            try:
                editor.setPlainText(read_combined_chapter(self.result, row) if self.result.kind == "combined" else decode_text(read_source(self.result.source, self.result.kind, row.name))[0])
            except Exception as exc:
                editor.setPlainText(str(exc))
            box.addWidget(editor)
            layout.addLayout(box, 1)
        dialog.exec()

    def mark_selection(self, decision):
        if self.result and self.result.kind == "combined":
            return
        if not self.result:
            return
        selected = [r for r in self.selected_files() if not r.virtual and not r.error]
        if not selected:
            return
        for row in selected:
            self.store.mark(self.result, row.name, decision)
        self.model.reset_rows(self.result.files)
        self.apply.setEnabled(False)
        self.set_result(self.result)

    def preview(self):
        if self.result and self.result.kind == "combined":
            QMessageBox.information(self, "อ่านอย่างเดียว", "TXT รวมบทไม่รองรับการจัดเลขไฟล์")
            return
        self.apply.setEnabled(False)
        if not self.result:
            QMessageBox.information(self, "ตรวจสอบก่อน", "ตรวจสอบไฟล์ก่อนจัดเลขบท")
            return
        try:
            self.plan = plan_renumber(self.result, self.start.value(), self.padding.value(), self.heading.isChecked())
        except Exception as exc:
            QMessageBox.warning(self, "ไม่สามารถจัดเลขบท", str(exc))
            return
        plan = self.plan
        changed = sum(f.target != f.original for f in plan.files if f.target is not None)
        excluded = sum(f.target is None for f in plan.files)
        kept = len(plan.files) - excluded
        self.plan_summary.setText(f"เดิม {len(plan.files)} · คัดออก {excluded} · คงเหลือ {kept} · เปลี่ยนชื่อ {changed} · ช่วง {plan.start}–{plan.start + kept - 1}")
        self.preview_table.setRowCount(len(plan.files))
        for i, file in enumerate(plan.files):
            for j, value in enumerate((file.original, file.target or "—",
                                       "คัดออก" if file.target is None else "คงเดิม" if file.target == file.original else "เปลี่ยนชื่อ")):
                self.preview_table.setItem(i, j, QTableWidgetItem(value))
        self.apply.setEnabled(True)

    def execute(self):
        if self.result and self.result.kind == "combined":
            return
        if not self.apply.isEnabled():
            return
        plan = self.plan
        if self.in_place.isChecked():
            if self.kind != "folder":
                QMessageBox.warning(self, "ZIP", "ZIP จะสร้างผลลัพธ์ใหม่เท่านั้น")
                return
            answer = QMessageBox.warning(self, "ยืนยันแก้ไฟล์ต้นฉบับ",
                                         "ระบบจะสำรองไฟล์ทั้งหมดก่อนเปลี่ยนชื่อ และคัดไฟล์ออกจากโฟลเดอร์ต้นฉบับ\nคุณยืนยันหรือไม่?",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        else:
            source = Path(plan.source)
            default = str(source.with_name(source.stem + "-inspected" + (".zip" if plan.kind == "zip" else "")))
            if plan.kind == "zip":
                destination, _ = QFileDialog.getSaveFileName(self, "บันทึก ZIP ใหม่", default, "ZIP (*.zip)")
            else:
                destination = QFileDialog.getExistingDirectory(self, "เลือกตำแหน่งเก็บโฟลเดอร์ผลลัพธ์", str(source.parent))
                if destination:
                    destination = str(Path(destination) / (source.name + "-inspected"))
            if not destination:
                return
        self.apply.setEnabled(False)
        self.write_worker = WriteWorker(plan, None if self.in_place.isChecked() else destination,
                                        self.in_place.isChecked(), self.store.root / "backups")
        self.write_worker.completed.connect(self.write_done)
        self.write_worker.failed.connect(self.write_failed)
        self.write_worker.finished.connect(self.post_write_rescan)
        self.write_worker.start()

    def write_done(self, operation):
        self.store.add_operation(operation, self.plan)
        self.refresh_history()
        QMessageBox.information(self, "เสร็จแล้ว", f"แก้ไฟล์เดิม {operation.get('changed', 0)} ไฟล์\nสำรอง: {operation.get('backup')}")
        output = operation.get("output") or (self.plan.source if operation.get("mode") == "in_place" else None)
        if output and Path(output).is_dir():
            self._post_write_output = output

    def post_write_rescan(self):
        output = self._post_write_output
        self._post_write_output = None
        if output:
            self.set_source(output, "folder")

    def write_failed(self, message):
        QMessageBox.critical(self, "จัดเลขบทไม่สำเร็จ",
                             f"{message}\nหากแก้ต้นฉบับ โปรดกู้คืนจาก Backup ที่เก็บไว้")

    def closeEvent(self, event):
        if (self.worker and self.worker.isRunning()) or (self.write_worker and self.write_worker.isRunning()):
            event.ignore()
            QMessageBox.warning(self, "กำลังทำงาน", "กรุณายกเลิกการสแกน หรือรอให้การเขียนไฟล์เสร็จก่อนปิดหน้าต่าง")
        else:
            super().closeEvent(event)

    def refresh_history(self):
        self.history_combo.clear()
        for item in self.store.history():
            self.history_combo.addItem(f"{item['time']} · {item['source']}", item['id'])
        self.operations_combo.clear()
        operations = self.store.operations()
        tracked_backups = {op.get("backup") for op in operations}
        for journal in sorted((self.store.root / "backups").glob("*/journal.json")):
            if str(journal.parent) in tracked_backups:
                continue
            try:
                entry = json.loads(journal.read_text(encoding="utf-8"))
                if entry.get("status") not in ("backing_up", "backup_complete", "applying", "recovery_required"):
                    continue
                operations.append({"time": "ต้องกู้คืน", "mode": entry["status"],
                                   "source": entry["source"], "backup": str(journal.parent), "id": entry["id"]})
            except (OSError, KeyError, ValueError):
                continue
        for operation in operations:
            self.operations_combo.addItem(f"{operation['time']} · {operation.get('mode')} · {operation['source']}", operation)

    def load_history(self):
        ident = self.history_combo.currentData()
        if ident:
            try:
                self.set_result(self.store.read_inspection(ident))

            except Exception as exc:
                QMessageBox.warning(self, "เปิดประวัติไม่ได้", str(exc))

    def restore(self):
        operation = self.operations_combo.currentData()
        if not operation or not operation.get("backup"):
            QMessageBox.information(self, "กู้คืน", "เลือกรายการที่มี Backup จากการแก้ต้นฉบับ")
            return
        destination = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์แม่สำหรับชุดข้อมูลที่กู้คืน", str(Path.home()))
        if not destination:
            return
        name = Path(operation["source"]).name + "-restored-" + operation["id"][:8]
        try:
            restored = restore_backup(operation["backup"], Path(destination) / name)
            QMessageBox.information(self, "กู้คืนสำเร็จ", f"สร้างชุดไฟล์แยกไว้ที่\n{restored}")
        except Exception as exc:
            QMessageBox.warning(self, "กู้คืนไม่ได้", str(exc))
