"""Review-first bulk chapter renumbering for the currently open Chinese source file."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .chapter_numbering import (
    chapter_issues, duplicate_heading_removal_plan, preview_renumber,
    scan_chapters, format_heading_number,
)
from .chapter_number_reference import resolve_translator_reference, should_auto_propose
from .storage import read_json, write_json


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _qt_position(text, offset):
    return len(text[:offset].encode("utf-16-le")) // 2


def _replace_headings(editor, original, headings, changes):
    """One undoable QTextCursor edit block, without replacing any story characters."""
    cursor = QTextCursor(editor.document())
    cursor.beginEditBlock()
    try:
        for index in sorted(changes, key=lambda i: headings[i].number_start, reverse=True):
            heading = headings[index]
            if changes[index] == heading.number:
                continue
            cursor.setPosition(_qt_position(original, heading.number_start))
            cursor.setPosition(_qt_position(original, heading.number_end), QTextCursor.KeepAnchor)
            cursor.insertText(format_heading_number(
                changes[index], original[heading.number_start:heading.number_end]
            ))
    finally:
        cursor.endEditBlock()



def apply_automatic_without_dialog(workspace, editor, path, expected, changes):
    """Apply a prevalidated contiguous plan without building a QTableWidget.

    Keep the identical undoable numeral-only edit, safety checks and audit event
    used by the manual dialog, but avoid one widget row per historical chapter.
    """
    original = editor.toPlainText()
    headings = scan_chapters(original)
    by_line = {heading.line: index for index, heading in enumerate(headings)}
    requested = {by_line[line]: corrected for line, _before, corrected in changes}
    planned, actual = preview_renumber(original, requested)
    if planned != expected or actual != changes:
        raise ValueError("เลขบทเปลี่ยนระหว่างตรวจ · ไม่แก้ต้นฉบับ")
    if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != editor.disk_digest:
        raise ValueError("ไฟล์ถูกแก้จากภายนอก · กรุณาตรวจความต่างก่อน")
    history_path = workspace.owner.repo.profile_dir(workspace.profile_id) / "chapter_numbering" / "history.json"
    history = read_json(history_path, {"events": []})
    if not isinstance(history, dict) or not isinstance(history.get("events"), list):
        raise ValueError("ประวัติแก้เลขบทมีโครงสร้างไม่ถูกต้อง")

    event_id = uuid.uuid4().hex
    snapshot = history_path.parent / (event_id + ".json")
    write_json(snapshot, {
        "profile_id": workspace.profile_id, "path": str(path), "text": original
    })
    event = {
        "id": event_id, "profile_id": workspace.profile_id,
        "path": str(path), "snapshot": snapshot.name,
        "before_sha256": _digest(original), "after_sha256": _digest(expected),
        "changes": [
            {"line": line, "original": before, "corrected": after}
            for line, before, after in changes
        ],
        "time": datetime.now(timezone.utc).isoformat(), "reverted": False,
    }
    _replace_headings(editor, original, headings, requested)
    if editor.toPlainText() != expected:
        editor.undo()
        raise ValueError("ข้อความหลังแก้ไม่ตรงกับ Preview · ย้อนการแก้แล้ว")
    if not workspace.editor.save_editor(editor, quiet=True, normalize=False):
        editor.undo()
        raise ValueError("บันทึกเลขบทใหม่ไม่สำเร็จ · คืนข้อความใน Editor แล้ว")
    history["events"].append(event)
    write_json(history_path, history)


class ChapterNumberDialog(QDialog):
    def __init__(self, workspace, editor, path: Path):
        super().__init__(workspace)
        self.workspace = workspace
        self.editor = editor
        self.path = path.resolve()
        self.profile_dir = workspace.owner.repo.profile_dir(workspace.profile_id)
        self.history_path = self.profile_dir / "chapter_numbering" / "history.json"
        self.original = editor.toPlainText()
        self.headings = scan_chapters(self.original)
        open_texts = {}
        for tab_index in range(workspace.editor.tabs.count()):
            opened = workspace.editor.tabs.widget(tab_index)
            opened_path = workspace.editor._path(opened)
            if opened_path is not None:
                open_texts[Path(opened_path).expanduser().resolve()] = opened.toPlainText()
        self.translator_reference = resolve_translator_reference(
            workspace.owner.repo, workspace.profile_id, self.path, open_texts
        )
        self.setWindowTitle("ตรวจเลขบทต้นฉบับ · " + self.path.name)
        self.resize(850, 580)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"ไฟล์: {self.path.name} · พบหัวบท {len(self.headings)} บท\n"
            "ตรวจและแก้เฉพาะไฟล์ต้นฉบับที่เปิดอยู่ · ไม่แก้ Translator/Context · ไม่มี Export\n"
            "เลขกระโดดอาจเกิดจากบทหายจริง โปรดตรวจเนื้อเรื่องก่อนยืนยัน"
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.reference_label = QLabel(self.translator_reference.message)
        self.reference_label.setObjectName("chapterTranslatorReference")
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)

        top = QHBoxLayout()
        top.addWidget(QLabel("เริ่มเรียงจากบท"))
        self.start_number = QSpinBox()
        self.start_number.setRange(1, 2_147_483_647)
        profile = next(
            (item for item in workspace.owner.repo.list_profiles()
             if item.id == workspace.profile_id), None
        )
        saved_start = getattr(profile, "chapter_manual_start", None)
        initial = (
            self.translator_reference.start
            or saved_start
            or (self.headings[0].number if self.headings else 1)
        )
        self.verified_prefix_count = 0
        if self.translator_reference.start is not None:
            from .incremental_chapter_numbering import verified_prefix_from_history
            checkpoint = verified_prefix_from_history(
                self.profile_dir, workspace.profile_id, self.path,
                self.original, self.translator_reference.start,
            )
            if checkpoint:
                self.verified_prefix_count = len(scan_chapters(checkpoint[0]))
                initial = self.translator_reference.start + self.verified_prefix_count
        self.start_number.setValue(initial)
        if self.translator_reference.start is None and saved_start:
            self.reference_label.setText(
                self.translator_reference.message
                + f" · เลขเริ่มต้นที่จำไว้ครั้งก่อน: {saved_start} (ไม่ใช้แก้อัตโนมัติ)"
            )
        # Connect after initialization: a Translator-derived suggestion is not
        # the user's manual preference and must not overwrite it.
        self.start_number.valueChanged.connect(self._remember_manual_start)
        top.addWidget(self.start_number)
        self.sequence_button = QPushButton("เรียงเลขต่อเนื่อง (เสนอ)")
        self.sequence_button.clicked.connect(self.propose_sequence)
        top.addWidget(self.sequence_button)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(len(self.headings), 5)
        self.table.setHorizontalHeaderLabels(
            ["เลือกแก้", "บรรทัด", "เลขเดิม / ชื่อบท", "เลขใหม่", "ผลตรวจ"]
        )
        self.table.setColumnWidth(0, 75)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 300)
        self.table.setColumnWidth(3, 120)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.checks = []
        self.spins = []
        issues = chapter_issues(self.headings, self.original)
        duplicate_count = sum("ซ้ำ" in issue for issue in issues)
        likely_duplicate_count = sum("น่าจะเป็นรายการเดียวกัน" in issue for issue in issues)
        gap_count = sum("กระโดด" in issue for issue in issues)
        reverse_count = sum("ย้อนกลับ" in issue for issue in issues)
        duplicate_summary = (
            f"สรุปผลตรวจ · หัวบท {len(self.headings)} · เลขซ้ำ {duplicate_count} "
            f"(หัวบทที่น่าจะซ้ำติดกัน {likely_duplicate_count}) · "
            f"เลขกระโดด {gap_count} · เลขย้อนกลับ {reverse_count}\n"
            "ระบบไม่ลบหัวบทหรือเปลี่ยนเลขให้อัตโนมัติ กรุณาดูเนื้อหาและตัวอย่างก่อนยืนยัน"
        )
        for i, heading in enumerate(self.headings):
            checkbox = QCheckBox()
            checkbox.setAccessibleName(f"แก้บทบรรทัด {heading.line}")
            self.table.setCellWidget(i, 0, checkbox)
            self.checks.append(checkbox)
            for col, value in (
                (1, str(heading.line)),
                (2, f"{heading.number} · {heading.title[:90]}"),
                (4, issues[i]),
            ):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, col, item)
            spin = QSpinBox()
            spin.setRange(1, 2_147_483_647)
            spin.setValue(heading.number)
            self.table.setCellWidget(i, 3, spin)
            self.spins.append(spin)
            spin.valueChanged.connect(lambda _value, check=checkbox: check.setChecked(True))
        layout.addWidget(self.table, 1)
        self.result = QLabel(
            duplicate_summary + "\nกดเรียงเลขต่อเนื่องเพื่อเสนอเลขใหม่ หรือแก้เลขทีละบท แล้วเลือกยืนยัน"
        )
        self.result.setWordWrap(True)
        layout.addWidget(self.result)

        actions = QHBoxLayout()
        reviewed = QPushButton("ตรวจแล้ว")
        reviewed.setToolTip("ยืนยันว่าได้ตรวจเลขบทแล้ว โดยไม่แก้เนื้อหา")
        reviewed.clicked.connect(self.accept)
        actions.addWidget(reviewed)
        self.selected_button = QPushButton("แก้ที่เลือก")
        self.selected_button.clicked.connect(self.apply_selected)
        actions.addWidget(self.selected_button)
        self.all_button = QPushButton("แก้ทั้งหมด")
        self.all_button.clicked.connect(self.apply_all)
        actions.addWidget(self.all_button)
        self.remove_duplicates_button = QPushButton("ลบหัวบทซ้ำ")
        self.remove_duplicates_button.setToolTip(
            "ลบเฉพาะหัวบทเลขและชื่อซ้ำที่อยู่ติดกัน โดยมี Preview และสำรองก่อนบันทึก"
        )
        self.remove_duplicates_button.setEnabled(likely_duplicate_count > 0)
        self.remove_duplicates_button.clicked.connect(self.remove_duplicate_headings)
        actions.addWidget(self.remove_duplicates_button)
        self.restore_button = QPushButton("ย้อนคืนการแก้ล่าสุด")
        self.restore_button.clicked.connect(self.restore_latest)
        actions.addWidget(self.restore_button)
        actions.addStretch(1)
        close = QPushButton("ปิด")
        close.clicked.connect(self.reject)
        actions.addWidget(close)
        layout.addLayout(actions)
        if self.translator_reference.path is not None and should_auto_propose(
            self.headings[self.verified_prefix_count:], initial
        ):
            self.propose_sequence()
            self.result.setText(
                f"เสนอเลขจาก {self.translator_reference.path.name} แล้ว · "
                "กรุณาตรวจความต่อเนื่องก่อนกดแก้ทั้งหมด"
            )
        self.sequence_button.setEnabled(bool(self.headings))
        self.selected_button.setEnabled(bool(self.headings))
        self.all_button.setEnabled(bool(self.headings))

    def remove_duplicate_headings(self):
        try:
            if self.editor.toPlainText() != self.original:
                raise ValueError("ข้อความเปลี่ยนหลังตรวจ กรุณาปิดแล้วตรวจใหม่")
            expected, removed_lines = duplicate_heading_removal_plan(self.original)
            if not removed_lines:
                QMessageBox.information(self, "ไม่พบหัวบทซ้ำที่ปลอดภัย", "ไม่มีหัวบทซ้ำติดกันที่เลขและชื่อบทตรงกัน")
                return
            if not self._file_unchanged():
                raise ValueError("ไฟล์ถูกแก้จากภายนอก · กรุณาตรวจความต่างก่อน")
            lines = self.original.splitlines()
            removed_text = "\n".join(f"บรรทัด {line}: {lines[line - 1]}" for line in removed_lines)
            kept = []
            removed = set(removed_lines)
            for heading in self.headings:
                if heading.line in removed and heading.line > 1:
                    previous = next((item for item in reversed(self.headings)
                                     if item.line < heading.line and item.line not in removed
                                     and item.number == heading.number
                                     and "".join(item.title.split()) == "".join(heading.title.split())), None)
                    if previous is not None:
                        kept.append(f"บรรทัด {previous.line}: {lines[previous.line - 1]}")
            preview = (
                f"ไฟล์: {self.path}\n\nก่อนแก้ · คงหัวบทแรกไว้:\n"
                + "\n".join(kept + ["ลบ: " + item.split(": ", 1)[1] for item in removed_text.splitlines()])
                + "\n\nหลังแก้:\n" + "\n".join(kept)
                + "\n\nลบเฉพาะบรรทัดหัวบทที่ระบุไว้ เนื้อหาบรรทัดอื่นจะคงเดิมและมีสำเนาสำรองสำหรับย้อนคืน."
            )
            if QMessageBox.question(
                self, "ตรวจ Preview ก่อนลบหัวบทซ้ำ", preview,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            ) != QMessageBox.Yes:
                return
            history = self._read_history()
            event = self._save_snapshot(self.original, expected, [])
            event["operation"] = "remove-duplicate-headings"
            event["removed_lines"] = removed_lines
            cursor = QTextCursor(self.editor.document())
            cursor.beginEditBlock()
            try:
                raw_lines = self.original.splitlines(keepends=True)
                offsets = []
                offset = 0
                for line in raw_lines:
                    offsets.append((offset, len(line)))
                    offset += len(line)
                for line_number in reversed(removed_lines):
                    start, length = offsets[line_number - 1]
                    cursor.setPosition(_qt_position(self.original, start))
                    cursor.setPosition(_qt_position(self.original, start + length), QTextCursor.KeepAnchor)
                    cursor.removeSelectedText()
            finally:
                cursor.endEditBlock()
            if self.editor.toPlainText() != expected:
                self.editor.undo()
                raise ValueError("ข้อความหลังแก้ไม่ตรงกับ Preview · ย้อนการแก้แล้ว")
            if not self.workspace.editor.save_editor(self.editor, quiet=True, normalize=False):
                self.editor.undo()
                raise ValueError("บันทึกการแก้หัวบทซ้ำไม่สำเร็จ · คืนข้อความใน Editor แล้ว")
            history["events"].append(event)
            write_json(self.history_path, history)
            QMessageBox.information(
                self, "แก้หัวบทซ้ำสำเร็จ",
                f"ลบหัวบทซ้ำ {len(removed_lines)} บรรทัดแล้ว · สำรองข้อความก่อนแก้ไว้สำหรับย้อนคืน",
            )
            self.accept()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "ลบหัวบทซ้ำไม่ได้", str(exc))

    def _remember_manual_start(self, value):
        profile = next(
            (p for p in self.workspace.owner.repo.list_profiles()
             if p.id == self.workspace.profile_id), None
        )
        if profile is not None:
            profile.chapter_manual_start = value
            self.workspace.owner.repo.save_profile(profile)

    def propose_sequence(self):
        first = self.start_number.value()
        if first + len(self.headings) - self.verified_prefix_count - 1 > 2_147_483_647:
            QMessageBox.warning(self, "เลขบทไม่ถูกต้อง", "เลขบทใหม่เกินช่วงที่รองรับ")
            return
        changed = 0
        for i, (heading, spin, check) in enumerate(zip(self.headings, self.spins, self.checks)):
            proposed = (
                heading.number if i < self.verified_prefix_count
                else first + i - self.verified_prefix_count
            )
            spin.setValue(proposed)
            check.setChecked(proposed != heading.number)
            changed += proposed != heading.number
        self.result.setText(
            f"เสนอแก้ {changed} บท · ลำดับที่เสนอยังไม่ยืนยันว่าบทไม่ขาดจริง"
        )

    def _proposal(self, all_rows):
        if self.editor.toPlainText() != self.original:
            raise ValueError("ข้อความเปลี่ยนหลังตรวจ กรุณาปิดแล้วตรวจใหม่")
        requested = {
            i: spin.value()
            for i, (spin, check) in enumerate(zip(self.spins, self.checks))
            if (all_rows or check.isChecked()) and spin.value() != self.headings[i].number
        }
        expected, changes = preview_renumber(self.original, requested)
        return requested, expected, changes

    def apply_all(self):
        self._apply(True)

    def apply_selected(self):
        self._apply(False)

    def apply_automatic(
        self, start: int, *, verified_prefix: str | None = None,
        previous_original: int | None = None,
    ) -> bool:
        """Reuse existing safe editor/backup path for a verified appended chapter."""
        from .incremental_chapter_numbering import automatic_append_plan
        try:
            _planned, changes = automatic_append_plan(
                self.original, start, verified_prefix, previous_original
            )
        except ValueError as exc:
            self.auto_error = str(exc)
            return False
        # Correct only chapter headers authorized by the validated append plan.
        # Earlier checked chapters never get proposed again.
        by_line = {heading.line: i for i, heading in enumerate(self.headings)}
        for checkbox in self.checks:
            checkbox.setChecked(False)
        for line, _before, after in changes:
            index = by_line[line]
            self.spins[index].setValue(after)
            self.checks[index].setChecked(True)
        return self._apply(False, automatic=True)

    def _read_history(self):
        data = read_json(self.history_path, {"events": []})
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise ValueError("ประวัติแก้เลขบทมีโครงสร้างไม่ถูกต้อง")
        return data

    def _save_snapshot(self, before, after, changes):
        directory = self.history_path.parent
        event_id = uuid.uuid4().hex
        backup = directory / (event_id + ".json")
        write_json(backup, {"profile_id": self.workspace.profile_id,
                            "path": str(self.path), "text": before})
        return {
            "id": event_id, "profile_id": self.workspace.profile_id,
            "path": str(self.path), "snapshot": backup.name,
            "before_sha256": _digest(before), "after_sha256": _digest(after),
            "changes": [{"line": line, "original": a, "corrected": b}
                        for line, a, b in changes],
            "time": datetime.now(timezone.utc).isoformat(),
            "reverted": False,
        }

    def _file_unchanged(self):
        return self.path.is_file() and hashlib.sha256(self.path.read_bytes()).digest() == self.editor.disk_digest

    def _apply(self, all_rows, *, automatic=False):
        try:
            requested, expected, changes = self._proposal(all_rows)
            if not changes:
                if not automatic:
                    QMessageBox.information(self, "ไม่พบรายการที่ต้องแก้", "ไม่มีเลขบทที่เลือกให้เปลี่ยน")
                return True
            if not self._file_unchanged():
                raise ValueError("ไฟล์ถูกแก้จากภายนอก · กรุณาตรวจความต่างก่อน")
            preview = "\n".join(f"บรรทัด {line}: {a} → {b}" for line, a, b in changes[:15])
            if len(changes) > 15:
                preview += f"\n…และอีก {len(changes) - 15} บท"
            if not automatic and QMessageBox.question(
                self, "ยืนยันแก้เลขบทต้นฉบับ",
                f"ไฟล์: {self.path.name}\nเปลี่ยน {len(changes)} หัวบท\n\n{preview}\n\n"
                "ตรวจว่าบทไม่ได้หายจริงก่อนยืนยัน · เปลี่ยนเฉพาะเลขหัวบท",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
            history = self._read_history()
            event = self._save_snapshot(self.original, expected, changes)
            _replace_headings(self.editor, self.original, self.headings, requested)
            if self.editor.toPlainText() != expected:
                self.editor.undo()
                raise ValueError("ข้อความหลังแก้ไม่ตรงกับ Preview · ย้อนการแก้แล้ว")
            if not self.workspace.editor.save_editor(self.editor, quiet=True, normalize=False):
                self.editor.undo()
                raise ValueError("ไม่สามารถบันทึกไฟล์ได้ · คืนข้อความใน Editor แล้ว")
            history["events"].append(event)
            write_json(self.history_path, history)
            if not automatic:
                QMessageBox.information(
                    self, "แก้เลขบทสำเร็จ",
                    f"แก้ {len(changes)} หัวบทใน {self.path.name} แล้ว\n"
                    "สำรองข้อความก่อนแก้ไว้สำหรับย้อนคืน\n"
                    "ไม่มีการ Export หรือแก้ไฟล์ Translator/Context"
                )
                self.accept()
            return True
        except (OSError, ValueError) as exc:
            if automatic:
                self.auto_error = str(exc)
            else:
                QMessageBox.warning(self, "ไม่สามารถแก้เลขบท", str(exc))
            return False

    def restore_latest(self):
        try:
            history = self._read_history()
            event = next(
                (item for item in reversed(history["events"])
                 if item.get("path") == str(self.path)
                 and item.get("profile_id") == self.workspace.profile_id
                 and not item.get("reverted")), None
            )
            if event is None:
                QMessageBox.information(self, "ย้อนคืน", "ไม่มีประวัติแก้เลขบทสำหรับไฟล์นี้")
                return
            if _digest(self.editor.toPlainText()) != event["after_sha256"] or not self._file_unchanged():
                raise ValueError("ไฟล์เปลี่ยนหลังแก้เลข ไม่ย้อนทับข้อมูลใหม่")
            snapshot_path = self.history_path.parent / event["snapshot"]
            if snapshot_path.parent.resolve() != self.history_path.parent.resolve():
                raise ValueError("ตำแหน่งสำรองไม่ปลอดภัย")
            backup = read_json(snapshot_path, None)
            if (not isinstance(backup, dict) or backup.get("profile_id") != self.workspace.profile_id
                    or backup.get("path") != str(self.path)
                    or _digest(backup.get("text", "")) != event["before_sha256"]):
                raise ValueError("ไม่สามารถยืนยันข้อมูลสำรองได้")
            if QMessageBox.question(
                self, "ย้อนคืนเลขบท", "คืนข้อความก่อนแก้เลขบทล่าสุดทั้งชุด?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            ) != QMessageBox.Yes:
                return
            cursor = QTextCursor(self.editor.document())
            cursor.beginEditBlock()
            cursor.select(QTextCursor.Document)
            cursor.insertText(backup["text"])
            cursor.endEditBlock()
            if not self.workspace.editor.save_editor(self.editor, quiet=True, normalize=False):
                self.editor.undo()
                raise ValueError("ไม่สามารถบันทึกการย้อนคืนได้")
            event["reverted"] = True
            write_json(self.history_path, history)
            QMessageBox.information(self, "ย้อนคืนสำเร็จ", "คืนข้อความก่อนแก้เลขบทล่าสุดแล้ว")
            self.accept()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.warning(self, "ย้อนคืนไม่ได้", str(exc))
