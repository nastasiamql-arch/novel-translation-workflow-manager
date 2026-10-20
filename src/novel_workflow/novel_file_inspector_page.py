"""Dedicated full-page inspector; intentionally independent from workflow stages."""
from __future__ import annotations

from pathlib import Path
import json
import threading

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QSpinBox, QSplitter, QTableView, QVBoxLayout,
    QWidget, QDialog, QTableWidget, QTableWidgetItem, QTabWidget,
)

from .novel_file_inspector import Inspection, inspect, read_source, decode_text
from .novel_file_inspector_history import InspectorStore
from .novel_file_inspector_renumber import (
    plan_renumber, execute_new, execute_in_place, restore_backup,
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
    HEADERS = ("บท", "ชื่อไฟล์", "ตัวอักษร", "ขนาด", "สถานะระบบ", "ผลตรวจของฉัน")

    def __init__(self):
        super().__init__()
        self.rows = []

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
            return self.HEADERS[section]
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
                      "—" if row.virtual else f"{row.size / 1024:.1f} KB",
                      row.error or ", ".join(row.reasons) or "ผ่านเกณฑ์ความยาว",
                      "ต้องตรวจใหม่" if row.review_stale else
                      {"keep": "เป็นนิยาย — เก็บไว้", "excluded": "คัดออก", "pending": "ยังไม่ตัดสินใจ"}.get(row.review, "—")]
            return values[c]
        if role == Qt.ToolTipRole:
            return row.error or ", ".join(row.reasons)
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
        if col == 3:
            return a.size < b.size
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
        self.source, self.kind = "", "folder"
        self._setup_ui()

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 2, 4, 4)
        root.setSpacing(10)
        source = QHBoxLayout()
        for label, handler in (("เลือกโฟลเดอร์ TXT", self.choose_folder),
                               ("เลือก ZIP", self.choose_zip)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            source.addWidget(button)
        self.profile_combo = QComboBox()
        self.profile_combo.addItem("เลือกนิยายใน NovelWorkflow", None)
        for profile in self.repo.list_profiles():
            self.profile_combo.addItem(profile.name, profile.id)
        source.addWidget(self.profile_combo)
        profile_button = QPushButton("เลือกต้นฉบับของนิยาย")
        profile_button.clicked.connect(self.choose_profile)
        source.addWidget(profile_button)
        root.addLayout(source)
        self.source_label = QLabel("ยังไม่ได้เลือกไฟล์ต้นฉบับ")
        self.source_label.setWordWrap(True)
        root.addWidget(self.source_label)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        review_page = QWidget()
        body = QVBoxLayout(review_page)
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
        body.addLayout(opts)
        controls = QHBoxLayout()
        self.scan_button = QPushButton("ตรวจสอบไฟล์")
        self.scan_button.clicked.connect(self.start_scan)
        controls.addWidget(self.scan_button)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_scan)
        controls.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        controls.addWidget(self.progress, 1)
        body.addLayout(controls)
        self.summary = QLabel("ไฟล์ทั้งหมด 0 · ผ่านเกณฑ์ 0 · น่าสงสัย 0 · เลขบทขาด 0")
        body.addWidget(self.summary)
        filters = QHBoxLayout()
        self.filter = QComboBox()
        for name, key in (("ทั้งหมด", "all"), ("น่าสงสัย", "suspicious"),
                          ("เลขบทขาด", "missing"), ("ไฟล์สั้น", "short"),
                          ("ไฟล์ซ้ำ", "duplicate")):
            self.filter.addItem(name, key)
        self.filter.currentIndexChanged.connect(self.update_filter)
        filters.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ค้นหาเลขบทหรือชื่อไฟล์")
        self.search.textChanged.connect(self.update_filter)
        filters.addWidget(self.search, 1)
        body.addLayout(filters)
        splitter = QSplitter(Qt.Vertical)
        self.model = FileTable()
        self.proxy = InspectorFilter()
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
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
        for label, slot in (("ก่อนหน้า", lambda: self.navigate_row(-1)),
                            ("ถัดไป", lambda: self.navigate_row(1)),
                            ("เปรียบเทียบ", self.compare_selected),
                            ("เป็นนิยาย — เก็บไว้", lambda: self.mark_selection("keep")),
                            ("คัดออก", lambda: self.mark_selection("excluded")),
                            ("ยังไม่ตัดสินใจ", lambda: self.mark_selection("pending"))):
            button = QPushButton(label)
            button.clicked.connect(slot)
            actions.addWidget(button)
        read_layout.addLayout(actions)
        splitter.addWidget(reader)
        splitter.setSizes([470, 330])
        body.addWidget(splitter, 1)
        self.tabs.addTab(review_page, "ตรวจสอบและอ่านเนื้อหา")

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
        self.tabs.addTab(renumber, "จัดเลขบทใหม่ · Preview")

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
        self.tabs.addTab(history, "ประวัติ / กู้คืน")
        self.refresh_history()

    def choose_folder(self):
        path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ TXT", self.source or str(Path.home()))
        if path:
            self.set_source(path, "folder")

    def choose_zip(self):
        path, _ = QFileDialog.getOpenFileName(self, "เลือก ZIP", self.source or str(Path.home()), "ZIP (*.zip)")
        if path:
            self.set_source(path, "zip")

    def choose_profile(self):
        pid = self.profile_combo.currentData()
        if not pid:
            QMessageBox.information(self, "เลือกนิยาย", "เลือกนิยายก่อน")
            return
        profile = next((p for p in self.repo.list_profiles() if p.id == pid), None)
        if not profile:
            return
        base = Path(profile.main_folder).expanduser() if profile.main_folder else self.repo.profile_dir(pid)
        preferred = base / "source" if (base / "source").is_dir() else base
        path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ต้นฉบับของนิยาย", str(preferred))
        if path:
            self.set_source(path, "folder")

    def set_source(self, path, kind):
        if (self.worker and self.worker.isRunning()) or (self.write_worker and self.write_worker.isRunning()):
            QMessageBox.warning(self, "กำลังตรวจสอบ", "รอให้การทำงานปัจจุบันสิ้นสุดก่อนเปลี่ยนแหล่งไฟล์")
            return
        self.source, self.kind = str(path), kind
        self.source_label.setText(f"{kind.upper()}: {path}")
        self.result = None
        self.model.reset_rows([])
        self.text.clear()
        self.apply.setEnabled(False)

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
        self.scan_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.worker.start()

    def cancel_scan(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)

    def progress_scan(self, n, total):
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(n)

    def finish_worker(self):
        self.scan_button.setEnabled(True)
        self.cancel_button.setEnabled(False)

    def scan_failed(self, message):
        QMessageBox.warning(self, "ตรวจสอบไม่สำเร็จ", message)

    def scan_done(self, result):
        if result.cancelled:
            self.detail.setText("ยกเลิกการตรวจแล้ว ผลลัพธ์บางส่วนไม่ได้บันทึก")
            return
        self.set_result(result)
        self.store.save_cache(result.source, result.kind, self.worker.cache)
        self.store.add_inspection(result)
        self.refresh_history()

    def set_result(self, result):
        self.result = result
        self.model.reset_rows(result.files)
        self.proxy.minimum = result.minimum
        self.proxy.invalidateFilter()
        s = result.summary()
        self.summary.setText(f"ไฟล์ทั้งหมด {s['total']:,} · ผ่านเกณฑ์ความยาว {s['length_pass']:,} · น่าสงสัย {s['suspicious']:,} · เลขบทขาด {s['missing']:,}")
        self.preview_table.setRowCount(0)
        self.apply.setEnabled(False)
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
        self.detail.setText(f"{row.name} · บท {row.chapter or '—'} · {row.count:,} ตัวอักษร · {row.size/1024:.1f} KB · "
                            + (row.error or ", ".join(row.reasons) or "ไม่มีข้อสงสัย"))
        if row.virtual or row.error:
            self.text.clear()
            return
        try:
            text, encoding = decode_text(read_source(self.result.source, self.result.kind, row.name))
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
                editor.setPlainText(decode_text(read_source(self.result.source, self.result.kind, row.name))[0])
            except Exception as exc:
                editor.setPlainText(str(exc))
            box.addWidget(editor)
            layout.addLayout(box, 1)
        dialog.exec()

    def mark_selection(self, decision):
        if not self.result:
            return
        selected = [r for r in self.selected_files() if not r.virtual and not r.error]
        if not selected:
            return
        for row in selected:
            self.store.mark(self.result, row.name, decision)
        self.model.reset_rows(self.result.files)
        self.apply.setEnabled(False)

    def preview(self):
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
        self.write_worker.start()

    def write_done(self, operation):
        self.store.add_operation(operation, self.plan)
        self.refresh_history()
        QMessageBox.information(self, "เสร็จแล้ว", f"สร้างผลลัพธ์สำเร็จ\n{operation.get('output', operation.get('backup'))}")

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
                self.tabs.setCurrentIndex(0)
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
