"""Bounded, non-destructive discovery of novel workflow files."""
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QLabel, QLineEdit, QVBoxLayout, QFileDialog, QPushButton, QWidget, QHBoxLayout, QMessageBox)

from .smart_folder_scan import scan_novel_folder, infer_novel_code, candidates_by_role


class SmartFolderDialog(QDialog):
    ROLE_LABELS = (("prompt", "Prompt · Project"), ("style", "Style · Project"),
        ("guideline", "ไกด์ไลน์การแปล · Project"), ("main", "ไฟล์หลักของนิยาย"),
        ("context", "Context"), ("glossary", "Glossary"),
        ("translator", "Translator"), ("novel", "Novel สำหรับหาศัพท์"),
        ("vocab_instruction", "คำสั่งหาศัพท์ · เลือกเอง"))

    def __init__(self, profile, parent=None, *, rescan=False, shared_instruction_path=None):
        super().__init__(parent)
        self.profile = profile
        self.shared_instruction_path = shared_instruction_path
        self.setWindowTitle("ตั้งค่าไฟล์ทั้งหมด · " + profile.name)
        self.resize(760, 650)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("ตรวจสอบรายการที่พบและแก้การจับคู่ก่อนบันทึก การสแกนไม่ลบหรือเขียนทับไฟล์เดิม"))
        form = QFormLayout()
        row = QFormLayout()
        self.folder = QLineEdit(profile.main_folder)
        row.addRow("โฟลเดอร์หลัก", self.folder)
        browse = QPushButton("เลือก…")
        browse.clicked.connect(self.choose_folder)
        row.addRow("", browse)
        self.code = QLineEdit(profile.novel_code)
        self.code.setPlaceholderText("รหัสนิยาย เช่น TQAOOP, IQO หรือ WET")
        row.addRow("รหัสนิยาย", self.code)
        root.addLayout(row)
        self.combos = {}
        self._scanned = []
        for role, label in self.ROLE_LABELS:
            combo = QComboBox(); combo.setObjectName("smartFile_" + role)
            combo.addItem("— ไม่เลือก —", "")
            self.combos[role] = combo
            selection = QWidget(); selection_row = QHBoxLayout(selection)
            selection_row.setContentsMargins(0, 0, 0, 0)
            selection_row.addWidget(combo, 1)
            choose = QPushButton("เลือกไฟล์…")
            choose.clicked.connect(lambda _checked=False, value=role: self.choose_file(value))
            selection_row.addWidget(choose)
            form.addRow(label, selection)
        root.addLayout(form)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)
        self.scan_button = QPushButton("สแกนโฟลเดอร์")
        self.scan_button.clicked.connect(self.scan)
        root.addWidget(self.scan_button)
        self.shared_instruction = QCheckBox("บันทึกไฟล์คำสั่งหาศัพท์นี้เป็นค่าเริ่มต้นส่วนกลาง")
        self.shared_instruction.setChecked(bool(shared_instruction_path and
            profile.vocabulary_instruction_path == shared_instruction_path))
        root.addWidget(self.shared_instruction)
        self.scan()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def choose_folder(self):
        current = self.folder.text().strip()
        path = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์นิยาย", current if Path(current).is_dir() else str(Path.home()))
        if path:
            self.folder.setText(path); self.scan()

    def choose_file(self, role):
        current = self.combos[role].currentData()
        start = str(Path(current).parent) if current and Path(current).parent.is_dir() else self.folder.text()
        path, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์ " + dict(self.ROLE_LABELS)[role], start, "ทุกไฟล์ (*)")
        if not path:
            return
        combo = self.combos[role]
        if combo.findData(path) < 0:
            combo.addItem(path, path)
        combo.setCurrentIndex(combo.findData(path))

    def accept(self):
        if not Path(self.folder.text().strip()).expanduser().is_dir():
            QMessageBox.warning(self, "เลือกโฟลเดอร์ก่อน", "โฟลเดอร์หลักไม่มีอยู่หรือยังไม่ได้เลือก")
            return
        super().accept()

    def scan(self):
        root = Path(self.folder.text()).expanduser()
        previous_selection = {role: combo.currentData() for role, combo in self.combos.items()} if self.combos else {}
        self._scanned = scan_novel_folder(root)
        code = infer_novel_code(self._scanned, self.code.text())
        if code:
            self.code.setText(code)
        candidates = candidates_by_role(self._scanned, code)
        # Existing, valid explicit links take precedence over suggestions.
        existing = {"context": self.profile.context_path,
                    "vocab_instruction": self.profile.vocabulary_instruction_path or self.shared_instruction_path}
        for step in [*self.profile.workflow.steps, self.profile.vocabulary_step]:
            if not step: continue
            for item in step.files:
                if not item.enabled or not item.path or not Path(item.path).is_file(): continue
                for role in candidates:
                    if item.file_type == role and role not in existing:
                        existing[role] = item.path
        for role, combo in self.combos.items():
            combo.blockSignals(True); combo.clear(); combo.addItem("— ไม่เลือก —", "")
            options = candidates.get(role, [])
            for path in options:
                combo.addItem(str(path), str(path))
            keep = previous_selection.get(role) or existing.get(role)
            if keep and Path(keep).is_file():
                if combo.findData(keep) < 0: combo.addItem(keep, keep)
                combo.setCurrentIndex(combo.findData(keep))
            elif len(options) == 1 and self._expected_location(role, options[0], root):
                combo.setCurrentIndex(1)
            else:
                combo.setCurrentIndex(0)
            combo.blockSignals(False)
        uncertain = sum(len(items) > 1 for items in candidates.values())
        self.summary.setText(f"พบไฟล์ {len(self._scanned)} รายการ · รหัสนิยาย: {code or 'ยังระบุไม่ได้'} · บทบาทที่กำกวม {uncertain} รายการ\n"
            "ขอบเขตสแกน: สูงสุด 10,000 ไฟล์ ลึก 8 ชั้น · ข้าม Backup, Recovery, Polish History, Cache และ Symbolic Link")

    @staticmethod
    def _expected_location(role, path, root):
        try:
            parent = Path(path).parent.resolve()
            root = Path(root).resolve()
            in_project = "project" in {part.casefold() for part in Path(path).parts}
            if role in {"prompt", "style", "guideline"}:
                return in_project
            if role == "vocab_instruction":
                return False
            return parent == root
        except OSError:
            return False
