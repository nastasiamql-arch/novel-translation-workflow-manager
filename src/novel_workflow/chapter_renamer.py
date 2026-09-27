from dataclasses import dataclass
import os
from pathlib import Path
import re
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


@dataclass(frozen=True)
class ChapterRename:
    old_path: Path
    new_path: Path
    status: str = "พร้อมเปลี่ยน"


def plan_chapter_renames(folder):
    """Preview four-digit padding for chapter filenames directly inside folder."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    pattern = re.compile(r"^บทที่\s*(\d+)(.*)$")
    plans = []
    for source in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
        if not source.is_file():
            continue
        match = pattern.match(source.stem)
        if not match:
            continue
        number, suffix = match.groups()
        padded = number.zfill(4)
        new_name = f"บทที่ {padded}{suffix}{source.suffix}"
        if new_name == source.name:
            continue
        plans.append(ChapterRename(source, source.with_name(new_name)))

    target_groups = {}
    for index, item in enumerate(plans):
        target_groups.setdefault(item.new_path.name.casefold(), []).append(index)

    moving_sources = {item.old_path.name.casefold() for item in plans}
    blocked = set()
    for indices in target_groups.values():
        if len(indices) > 1:
            blocked.update(indices)
    for index, item in enumerate(plans):
        if item.new_path.exists() and item.new_path.name.casefold() not in moving_sources:
            blocked.add(index)

    return [
        ChapterRename(item.old_path, item.new_path, "ชื่อซ้ำ—ข้าม" if index in blocked else item.status)
        for index, item in enumerate(plans)
    ]


def apply_chapter_renames(plans):
    """Rename a checked batch through temporary names and roll back on failure."""
    changes = [item for item in plans if item.status == "พร้อมเปลี่ยน"]
    destinations = [item.new_path.name.casefold() for item in changes]
    if len(destinations) != len(set(destinations)):
        raise FileExistsError("มีชื่อปลายทางซ้ำกัน")
    moving = {item.old_path.resolve() for item in changes}
    for item in changes:
        if item.new_path.exists() and item.new_path.resolve() not in moving:
            raise FileExistsError(f"มีไฟล์ชื่อนี้อยู่แล้ว: {item.new_path.name}")

    staged = []
    completed = []
    try:
        for item in changes:
            temporary = item.old_path.with_name(
                f".{item.old_path.stem}.rename-{uuid.uuid4().hex}{item.old_path.suffix}"
            )
            item.old_path.rename(temporary)
            staged.append((item, temporary))
        for item, temporary in staged:
            temporary.rename(item.new_path)
            completed.append(item)
    except OSError:
        for item in reversed(completed):
            if item.new_path.exists() and not item.old_path.exists():
                item.new_path.rename(item.old_path)
        for item, temporary in reversed(staged):
            if temporary.exists() and not item.old_path.exists():
                temporary.rename(item.old_path)
        raise
    return {item.old_path.resolve(): item.new_path.resolve() for item in changes}


class ChapterRenameDialog(QDialog):
    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self.setWindowTitle("จัดเลขบทในชื่อไฟล์")
        self.resize(900, 560)
        self.renamed = {}
        self.plans = plan_chapter_renames(folder)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"โฟลเดอร์: {Path(folder)}"))
        ready = sum(item.status == "พร้อมเปลี่ยน" for item in self.plans)
        skipped = len(self.plans) - ready
        self.summary = QLabel(
            f"พบไฟล์ที่ต้องจัดชื่อ {len(self.plans)} ไฟล์ · พร้อมเปลี่ยน {ready} · ข้ามเพราะชื่อซ้ำ {skipped}"
        )
        layout.addWidget(self.summary)

        self.table = QTableWidget(len(self.plans), 3)
        self.table.setHorizontalHeaderLabels(["ชื่อเดิม", "ชื่อใหม่", "สถานะ"])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(0, self.table.horizontalHeader().ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, self.table.horizontalHeader().Stretch)
        for row, item in enumerate(self.plans):
            for column, value in enumerate((item.old_path.name, item.new_path.name, item.status)):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                if column == 2 and item.status != "พร้อมเปลี่ยน":
                    cell.setForeground(Qt.darkRed)
                self.table.setItem(row, column, cell)
        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.apply_button = buttons.addButton("เปลี่ยนชื่อไฟล์", QDialogButtonBox.AcceptRole)
        self.apply_button.setEnabled(ready > 0)
        buttons.rejected.connect(self.reject)
        self.apply_button.clicked.connect(self.apply)
        layout.addWidget(buttons)

    def apply(self):
        try:
            self.renamed = apply_chapter_renames(self.plans)
        except OSError as exc:
            QMessageBox.critical(self, "เปลี่ยนชื่อไม่สำเร็จ", str(exc))
            return
        QMessageBox.information(
            self, "เสร็จแล้ว", f"เปลี่ยนชื่อไฟล์สำเร็จ {len(self.renamed)} ไฟล์"
        )
        self.accept()
