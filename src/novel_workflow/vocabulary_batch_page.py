"""Two simple TXT-based vocabulary tools inside the existing novel workspace.

Reading, previewing, and selecting sources never mutate source files, export
records, translation steps, or the clipboard. Clipboard copy is user initiated.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from .vocabulary_batches import (
    batch_clipboard_text, existing_chapter_targets, make_chapter_batches,
    parse_pasted_chapters, read_utf8_text, scan_chapter_files,
    split_missing_numbers, write_split_chapters,
)


class TxtVocabularyPage(QWidget):
    """Read-only TXT batch copying and explicit preview-then-save splitting."""

    def __init__(self, state: dict, changed, default_folder: Path, parent=None):
        super().__init__(parent)
        self.changed = changed
        self.default_folder = Path(default_folder)
        self.state = dict(state) if isinstance(state, dict) else {}
        self.state.setdefault("folder", str(self.default_folder))
        self.state.setdefault("batch_size", 5)
        self.state.setdefault("start", 0)
        self.state.setdefault("end", 0)
        self.state.setdefault("glossary_1", "")
        self.state.setdefault("glossary_2", "")
        self._segments = ()
        self._preview_input = None
        self.setObjectName("txtVocabularyPage")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 6, 12, 8)
        title = QLabel("หาคำศัพท์จาก TXT")
        title.setObjectName("sectionHeading")
        root.addWidget(title)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("txtVocabularyTabs")
        root.addWidget(self.tabs, 1)

        batch_page = QWidget()
        batch_layout = QVBoxLayout(batch_page)
        batch_layout.setSpacing(9)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("โฟลเดอร์ต้นฉบับ"))
        self.folder_label = QLabel()
        self.folder_label.setObjectName("mutedLabel")
        self.folder_label.setMinimumWidth(0)
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        folder_row.addWidget(self.folder_label, 1)
        select_folder = QPushButton("เลือกโฟลเดอร์")
        select_folder.setObjectName("txtVocabularyChooseFolder")
        select_folder.clicked.connect(self.choose_folder)
        folder_row.addWidget(select_folder)
        batch_layout.addLayout(folder_row)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("บทต่อชุด"))
        self.batch_size = QSpinBox()
        self.batch_size.setObjectName("txtVocabularyBatchSize")
        self.batch_size.setRange(1, 100)
        self.batch_size.setValue(max(1, min(100, int(self.state.get("batch_size") or 5))))
        controls.addWidget(self.batch_size)
        controls.addWidget(QLabel("เริ่ม"))
        self.start = QSpinBox()
        self.start.setObjectName("txtVocabularyStart")
        self.start.setRange(0, 999999)
        self.start.setSpecialValueText("อัตโนมัติ")
        self.start.setValue(max(0, int(self.state.get("start") or 0)))
        controls.addWidget(self.start)
        controls.addWidget(QLabel("ถึง"))
        self.end = QSpinBox()
        self.end.setObjectName("txtVocabularyEnd")
        self.end.setRange(0, 999999)
        self.end.setSpecialValueText("อัตโนมัติ")
        self.end.setValue(max(0, int(self.state.get("end") or 0)))
        controls.addWidget(self.end)
        reload_button = QPushButton("รีเฟรช")
        reload_button.setObjectName("txtVocabularyRefresh")
        reload_button.clicked.connect(self.refresh)
        controls.addWidget(reload_button)
        controls.addStretch(1)
        batch_layout.addLayout(controls)

        self.glossary_labels = []
        for n in (1, 2):
            row = QHBoxLayout()
            row.addWidget(QLabel(f"คำศัพท์อ้างอิง {n}"))
            label = QLabel()
            label.setObjectName("mutedLabel")
            label.setMinimumWidth(0)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self.glossary_labels.append(label)
            row.addWidget(label, 1)
            choose = QPushButton("เลือกไฟล์")
            choose.setObjectName(f"txtVocabularyChooseGlossary{n}")
            choose.clicked.connect(lambda checked=False, i=n: self.choose_glossary(i))
            row.addWidget(choose)
            batch_layout.addLayout(row)
        self.summary = QLabel()
        self.summary.setObjectName("mutedLabel")
        self.summary.setWordWrap(True)
        batch_layout.addWidget(self.summary)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self.cards = QWidget()
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(8)
        scroll.setWidget(self.cards)
        batch_layout.addWidget(scroll, 1)
        self.tabs.addTab(batch_page, "คัดลอกเป็นชุด")

        paste_page = QWidget()
        paste_layout = QVBoxLayout(paste_page)
        paste_layout.setSpacing(9)
        hint = QLabel("วางต้นฉบับหลายบทครั้งเดียว แล้วตรวจหัวบทก่อนสร้างไฟล์ TXT · ไม่เขียนทับอัตโนมัติ")
        hint.setWordWrap(True)
        hint.setObjectName("mutedLabel")
        paste_layout.addWidget(hint)
        self.pasted_text = QPlainTextEdit()
        self.pasted_text.setObjectName("txtVocabularyPastedText")
        self.pasted_text.setPlaceholderText(
            "第一章 开始\nเนื้อหาบทที่หนึ่ง...\n\n第二章 觉醒\nเนื้อหาบทที่สอง...\n\n"
            "รองรับ 第100章, บทที่ 1, ตอนที่ 1, Chapter 1"
        )
        self.pasted_text.setMinimumHeight(140)
        paste_layout.addWidget(self.pasted_text, 2)
        preview_row = QHBoxLayout()
        self.preview_button = QPushButton("ตรวจหัวบทและแสดงตัวอย่าง")
        self.preview_button.setObjectName("txtVocabularyPreview")
        self.preview_button.clicked.connect(self.preview_paste)
        preview_row.addWidget(self.preview_button)
        self.paste_summary = QLabel("ยังไม่ได้ตรวจข้อความ")
        self.paste_summary.setObjectName("mutedLabel")
        self.paste_summary.setWordWrap(True)
        preview_row.addWidget(self.paste_summary, 1)
        paste_layout.addLayout(preview_row)
        self.preview_table = QTableWidget(0, 3)
        self.preview_table.setObjectName("txtVocabularyPreviewTable")
        self.preview_table.setHorizontalHeaderLabels(["บท", "ชื่อไฟล์ที่จะสร้าง", "บรรทัดต้นฉบับ"])
        self.preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.itemSelectionChanged.connect(self.show_preview_chapter)
        paste_layout.addWidget(self.preview_table, 2)
        self.chapter_preview = QPlainTextEdit()
        self.chapter_preview.setObjectName("txtVocabularyChapterPreview")
        self.chapter_preview.setReadOnly(True)
        self.chapter_preview.setPlaceholderText("เลือกบทด้านบนเพื่อดูเนื้อหาตั้งแต่หัวบทจนถึงก่อนบทถัดไป")
        self.chapter_preview.setMinimumHeight(90)
        paste_layout.addWidget(self.chapter_preview, 1)
        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("บันทึกไปยัง"))
        self.destination_label = QLabel()
        self.destination_label.setMinimumWidth(0)
        self.destination_label.setObjectName("mutedLabel")
        dest_row.addWidget(self.destination_label, 1)
        choose_destination = QPushButton("เลือกปลายทาง")
        choose_destination.setObjectName("txtVocabularyChooseDestination")
        choose_destination.clicked.connect(self.choose_destination)
        dest_row.addWidget(choose_destination)
        paste_layout.addLayout(dest_row)
        self.save_button = QPushButton("ยืนยันและแยกเป็นไฟล์ TXT")
        self.save_button.setObjectName("txtVocabularySaveSplit")
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save_paste)
        paste_layout.addWidget(self.save_button)
        self.tabs.addTab(paste_page, "วางหลายบท → แยกไฟล์")

        self.batch_size.valueChanged.connect(self._configuration_changed)
        self.start.valueChanged.connect(self._configuration_changed)
        self.end.valueChanged.connect(self._configuration_changed)
        self.pasted_text.textChanged.connect(self.invalidate_preview)
        self._update_labels()
        self.refresh()

    def _save(self):
        self.state["batch_size"] = self.batch_size.value()
        self.state["start"] = self.start.value()
        self.state["end"] = self.end.value()
        self.changed(dict(self.state))

    def _configuration_changed(self, _value):
        self._save()
        self.refresh()

    def _update_labels(self):
        folder = str(self.state.get("folder") or self.default_folder)
        self.folder_label.setText(folder)
        self.folder_label.setToolTip(folder)
        destination = str(self.state.get("destination") or folder)
        self.destination_label.setText(destination)
        self.destination_label.setToolTip(destination)
        for n, label in enumerate(self.glossary_labels, 1):
            file = str(self.state.get(f"glossary_{n}") or "")
            label.setText(Path(file).name if file else "ยังไม่เลือก")
            label.setToolTip(file)

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์ TXT", str(self.state.get("folder") or self.default_folder)
        )
        if folder:
            self.state["folder"] = folder
            self.state["destination"] = folder
            self._update_labels()
            self._save()
            self.refresh()

    def choose_destination(self):
        folder = QFileDialog.getExistingDirectory(
            self, "เลือกโฟลเดอร์บันทึกไฟล์ที่แยก",
            str(self.state.get("destination") or self.state.get("folder") or self.default_folder),
        )
        if folder:
            self.state["destination"] = folder
            self._update_labels()
            self._save()

    def choose_glossary(self, index: int):
        current = str(self.state.get(f"glossary_{index}") or self.state.get("folder") or "")
        path, _ = QFileDialog.getOpenFileName(
            self, f"เลือกไฟล์คำศัพท์อ้างอิง {index}", current,
            "Text files (*.txt *.md *.markdown);;All files (*)",
        )
        if path:
            self.state[f"glossary_{index}"] = path
            self._update_labels()
            self._save()
            self.refresh()

    def _clear_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()

    def refresh(self):
        self._clear_cards()
        try:
            chapters = scan_chapter_files(self.state.get("folder") or self.default_folder)
            if not chapters:
                self.summary.setText("ยังไม่มีไฟล์ TXT ที่ขึ้นต้นด้วยเลขบท เช่น 0001.txt หรือ 0001 ชื่อตอน.txt")
                return
            groups = make_chapter_batches(
                chapters, self.batch_size.value(),
                self.start.value() or None, self.end.value() or None,
            )
        except (OSError, ValueError) as exc:
            self.summary.setText(str(exc))
            return
        missing_count = sum(len(b.missing) for b in groups)
        self.summary.setText(
            f"พบ {len(chapters)} ไฟล์บท · {len(groups)} ชุด · บท {groups[0].start:04d}–{groups[-1].end:04d}"
            + (f" · ขาด {missing_count} บท (จะแจ้งก่อนคัดลอก)" if missing_count else "")
        )
        for group in groups[:250]:
            card = QFrame()
            card.setObjectName("txtVocabularyCard")
            card.setFrameShape(QFrame.StyledPanel)
            layout = QVBoxLayout(card)
            line = QHBoxLayout()
            line.addWidget(QLabel(f"ชุดที่ {group.index}  ·  บท {group.start:04d}–{group.end:04d}"), 1)
            count = QLabel(f"{len(group.chapters)} บท")
            count.setObjectName("mutedLabel")
            line.addWidget(count)
            layout.addLayout(line)
            files = QLabel(" · ".join(item.path.name for item in group.chapters) or "ไม่มีไฟล์ในช่วงนี้")
            files.setObjectName("mutedLabel")
            files.setWordWrap(True)
            layout.addWidget(files)
            if group.missing:
                warning = QLabel("บทที่ขาด: " + ", ".join(f"{i:04d}" for i in group.missing[:20])
                                 + ("…" if len(group.missing) > 20 else ""))
                warning.setWordWrap(True)
                warning.setObjectName("mutedLabel")
                layout.addWidget(warning)
            buttons = QHBoxLayout()
            copy = QPushButton("คัดลอกต้นฉบับ")
            copy.setObjectName(f"txtVocabularyCopyBatch{group.index}")
            copy.setEnabled(bool(group.chapters))
            copy.clicked.connect(lambda checked=False, b=group, button=copy: self.copy_batch(b, button))
            buttons.addWidget(copy)
            for index in (1, 2):
                reference = QPushButton(f"คัดลอกคำศัพท์ {index}")
                reference.setObjectName(f"txtVocabularyCopyGlossary{index}Batch{group.index}")
                reference.setEnabled(bool(self.state.get(f"glossary_{index}")))
                reference.clicked.connect(
                    lambda checked=False, i=index, button=reference: self.copy_glossary(i, button)
                )
                buttons.addWidget(reference)
            buttons.addStretch(1)
            layout.addLayout(buttons)
            self.cards_layout.addWidget(card)
        if len(groups) > 250:
            self.cards_layout.addWidget(QLabel("แสดง 250 ชุดแรก กรุณากำหนดช่วงบทเพื่อดูชุดถัดไป"))
        self.cards_layout.addStretch()

    def _copy(self, contents: str, button: QPushButton):
        QApplication.clipboard().setText(contents)
        button.setText("✓ คัดลอกแล้ว")

    def copy_batch(self, group, button: QPushButton):
        if group.missing:
            response = QMessageBox.question(
                self, "มีเลขบทขาด",
                "บทที่ขาด: " + ", ".join(f"{n:04d}" for n in group.missing[:30])
                + "\nคัดลอกเฉพาะบทที่มีไฟล์อยู่ใช่หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if response != QMessageBox.Yes:
                return
        try:
            text = batch_clipboard_text(group)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "คัดลอกไม่สำเร็จ", str(exc))
            return
        self._copy(text, button)

    def copy_glossary(self, number: int, button: QPushButton):
        path = self.state.get(f"glossary_{number}")
        if not path:
            return
        try:
            contents = read_utf8_text(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "คัดลอกคำศัพท์ไม่สำเร็จ", str(exc))
            return
        self._copy(contents, button)

    def invalidate_preview(self):
        self._segments = ()
        self._preview_input = None
        self.save_button.setEnabled(False)
        self.paste_summary.setText("เนื้อหาเปลี่ยนแล้ว กรุณาตรวจหัวบทอีกครั้ง")
        self.preview_table.setRowCount(0)
        self.chapter_preview.clear()

    def preview_paste(self):
        contents = self.pasted_text.toPlainText()
        try:
            segments = parse_pasted_chapters(contents)
        except ValueError as exc:
            self.invalidate_preview()
            self.paste_summary.setText(str(exc))
            return
        self._segments = segments
        self._preview_input = contents
        self.preview_table.setRowCount(len(segments))
        for row, segment in enumerate(segments):
            for col, value in enumerate((
                f"{segment.number:04d}", segment.filename, str(segment.first_line),
            )):
                self.preview_table.setItem(row, col, QTableWidgetItem(value))
        self.preview_table.resizeColumnsToContents()
        missing = split_missing_numbers(segments)
        self.paste_summary.setText(
            f"ตรวจพบ {len(segments)} บท"
            + (f" · เลขบทขาด {len(missing)} บท เช่น {', '.join(str(i) for i in missing[:10])}"
               if missing else " · เลขบทต่อเนื่อง")
            + " · เลือกบทเพื่อตรวจเนื้อหาแล้วกดยืนยันบันทึก"
        )
        self.save_button.setEnabled(True)
        if segments:
            self.preview_table.selectRow(0)

    def show_preview_chapter(self):
        row = self.preview_table.currentRow()
        if 0 <= row < len(self._segments):
            self.chapter_preview.setPlainText(self._segments[row].text)
        else:
            self.chapter_preview.clear()

    def save_paste(self):
        if not self._segments or self._preview_input != self.pasted_text.toPlainText():
            self.invalidate_preview()
            return
        folder = Path(self.state.get("destination") or self.state.get("folder") or self.default_folder)
        if not folder.is_dir():
            QMessageBox.warning(self, "บันทึกไม่ได้", f"ไม่พบโฟลเดอร์ปลายทาง: {folder}")
            return
        try:
            conflicts = existing_chapter_targets(folder, self._segments)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "ตรวจไฟล์เดิมไม่สำเร็จ", str(exc))
            return
        mode = "skip"
        if conflicts:
            dialog = QMessageBox(self)
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("พบเลขบทที่มีไฟล์แล้ว")
            dialog.setText(
                f"พบ {len(conflicts)} บทที่มีไฟล์อยู่แล้ว\n"
                "เลือกข้าม (ปลอดภัยที่สุด) หรือแทนที่โดยสำรองไฟล์เดิมก่อน"
            )
            skip = dialog.addButton("ข้ามบทที่มีอยู่", QMessageBox.AcceptRole)
            replace = dialog.addButton("สำรองแล้วแทนที่", QMessageBox.DestructiveRole)
            dialog.addButton("ยกเลิก", QMessageBox.RejectRole)
            dialog.setDefaultButton(skip)
            dialog.exec()
            if dialog.clickedButton() is replace:
                mode = "replace"
            elif dialog.clickedButton() is not skip:
                return
        else:
            if QMessageBox.question(
                self, "ยืนยันแยกไฟล์",
                f"สร้างไฟล์ TXT จำนวน {len(self._segments)} บทในโฟลเดอร์\n{folder}\n"
                "เนื้อหาต้นฉบับในช่องวางจะไม่ถูกลบ",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
        try:
            result = write_split_chapters(folder, self._segments, on_existing=mode)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "แยกไฟล์ไม่สำเร็จ", str(exc))
            return
        self.state["folder"] = str(folder)
        self._update_labels()
        self._save()
        self.refresh()
        self.tabs.setCurrentIndex(0)
        message = f"สร้าง {result.written} ไฟล์ · ข้าม {result.skipped} บท"
        if result.backup_directory:
            message += f"\nสำรองไฟล์ที่แทนที่ไว้ใน {result.backup_directory}"
        QMessageBox.information(self, "แยกไฟล์เสร็จแล้ว", message)
