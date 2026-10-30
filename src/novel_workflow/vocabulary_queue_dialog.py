from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTextEdit, QVBoxLayout)
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
        self.combined_text = QTextEdit(self)
        self.combined_text.setObjectName('pendingVocabularyText')
        self.combined_text.setReadOnly(True)
        layout.addWidget(self.combined_text, 1)
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
        self.summary.setText(
            f"นิยาย: {self.profile.name}\nรอตรวจทั้งหมด: {sum(x['count'] for x in items)} คำศัพท์"
        )
        self.combined_text.setPlainText(self._combined_text(items))
        if self.changed:
            self.changed()

    @staticmethod
    def _combined_text(items):
        # Keep transactionally separate queue records, but render one document.
        return '\n'.join(row['text'] for row in items)

    def copy_all(self):
        if self.data['items']:
            QApplication.clipboard().setText(self._combined_text(self.data['items']))

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
