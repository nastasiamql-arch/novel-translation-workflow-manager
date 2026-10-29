from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget)
from .vocabulary_queue import load_queue, save_queue


class VocabularyQueueDialog(QDialog):
    def __init__(self, repo, profile, parent=None, changed=None):
        super().__init__(parent)
        self.repo, self.profile, self.changed = repo, profile, changed
        self.setWindowTitle('คำศัพท์รอตรวจ')
        self.resize(620, 480)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        area = QScrollArea()
        area.setWidgetResizable(True)
        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        area.setWidget(self.body)
        layout.addWidget(area)
        actions = QHBoxLayout()
        copy_all = QPushButton('คัดลอกทั้งหมด')
        copy_all.clicked.connect(self.copy_all)
        clear_all = QPushButton('ล้างทั้งหมด')
        clear_all.clicked.connect(self.clear_all)
        close = QPushButton('ปิด')
        close.clicked.connect(self.accept)
        for button in (copy_all, clear_all, close): actions.addWidget(button)
        layout.addLayout(actions)
        self.refresh()

    def refresh(self):
        self.data = load_queue(self.repo, self.profile.id)
        items = self.data['items']
        self.summary.setText(f"นิยาย: {self.profile.name}\nรอตรวจ: {sum(x['count'] for x in items)} คำศัพท์ · จำนวนชุด: {len(items)}")
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        if not items:
            self.rows.addWidget(QLabel('ไม่มีคำศัพท์รอตรวจ'))
        for row in items:
            box = QWidget()
            layout = QVBoxLayout(box)
            layout.addWidget(QLabel(f"บท {row.get('chapter_range') or 'ไม่ระบุ'} · {row['count']} คำศัพท์ · Export: {row.get('created_at', '')}"))
            text = QTextEdit()
            text.setReadOnly(True)
            text.setPlainText(row['text'])
            text.setMinimumHeight(90)
            layout.addWidget(text)
            actions = QHBoxLayout()
            copy = QPushButton('คัดลอกชุดนี้')
            copy.clicked.connect(lambda checked=False, value=row['text']: QApplication.clipboard().setText(value))
            remove = QPushButton('ลบชุดนี้')
            remove.clicked.connect(lambda checked=False, value=row: self.remove(value))
            actions.addWidget(copy); actions.addWidget(remove)
            layout.addLayout(actions)
            self.rows.addWidget(box)
        self.rows.addStretch()
        if self.changed: self.changed()

    def copy_all(self):
        if self.data['items']:
            QApplication.clipboard().setText('\n'.join(row['text'] for row in self.data['items']))

    def remove(self, row):
        if QMessageBox.question(self, 'ลบคำศัพท์', f"ต้องการลบคำศัพท์ชุดนี้จำนวน {row['count']} รายการหรือไม่?") != QMessageBox.Yes:
            return
        self._delete({row['id']})

    def clear_all(self):
        items = self.data['items']
        if not items: return
        if QMessageBox.question(self, 'ล้างคำศัพท์', f"ต้องการลบคำศัพท์รอตรวจทั้งหมด {len(items)} ชุด รวม {sum(x['count'] for x in items)} รายการหรือไม่?") != QMessageBox.Yes:
            return
        self._delete({x['id'] for x in items})

    def _delete(self, ids):
        try:
            with self.repo.profile_lock:
                current = load_queue(self.repo, self.profile.id)
                current['items'] = [x for x in current['items'] if x['id'] not in ids]
                save_queue(self.repo, self.profile.id, current)
            self.refresh()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, 'ลบไม่สำเร็จ', str(exc))
