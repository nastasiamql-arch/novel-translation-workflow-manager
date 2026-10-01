"""Per-novel panel and cancellable background pipeline."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox,
    QCheckBox, QScrollArea)

from .credentials import CredentialStore
from .providers import create_provider
from .services import ProfileService
from .vocabulary import run_vocabulary, Cancelled


PHASES = {"snapshot": "อ่านไฟล์", "extract": "1. กำลังหาศัพท์…", "polish": "2. กำลังเกลาศัพท์…",
          "validate": "3. ตรวจผล", "backup": "4. สำรอง VOCAB", "commit": "5. อัปเดต VOCAB"}


class VocabularyWorker(QThread):
    phase = Signal(str)

    def __init__(self, settings, provider, key, parent=None):
        super().__init__(parent)
        self.settings, self.provider, self.key = deepcopy(settings), provider, key
        self.result = self.error = None

    def run(self):
        try:
            self.result = run_vocabulary(self.settings, self.provider, self.key,
                progress=self.phase.emit, cancelled=self.isInterruptionRequested)
        except Cancelled:
            self.error = "ยกเลิกแล้ว"
        except (ValueError, OSError, UnicodeError):
            # Never show exception bodies which could include source text or credentials.
            self.error = "ทำงานไม่สำเร็จ ตรวจไฟล์ รูปแบบ VOCAB/ผล AI และการตั้งค่า API แล้วลองใหม่"
        except Exception:
            self.error = "เกิดข้อผิดพลาดระหว่างทำงาน VOCAB ไม่ถูกเขียนจากผลที่ไม่ผ่านการตรวจ"
        finally:
            self.key = ""


class VocabularyPanel(QWidget):
    def __init__(self, repo, profile, open_file, prepare=lambda path: True, release=lambda path: None, parent=None):
        super().__init__(parent)
        self.repo, self.profile = repo, profile
        self.open_file, self.prepare, self.release = open_file, prepare, release
        self.credentials = CredentialStore(repo.root / "credentials")
        self.worker = None
        self.setObjectName("vocabularyPanel")
        self.setMinimumWidth(42)
        self.setMaximumWidth(380)
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.toggle_button = QPushButton("หาศัพท์ ‹")
        self.toggle_button.clicked.connect(self.toggle)
        header.addWidget(self.toggle_button)
        layout.addLayout(header)
        self.body = QScrollArea()
        self.body.setWidgetResizable(True)
        self.body.setMinimumWidth(250)
        content = QWidget()
        body = QVBoxLayout(content)
        self.labels, self.controls = {}, []
        fields = [("source_path", "ไฟล์เนื้อหา"), ("vocab_path", "ไฟล์ VOCAB"),
                  ("extract_prompt_path", "Prompt หาศัพท์"), ("polish_prompt_path", "Prompt เกลาศัพท์")]
        for field, label in fields:
            body.addWidget(QLabel(label))
            value = QLabel()
            value.setWordWrap(True)
            self.labels[field] = value
            body.addWidget(value)
            row = QHBoxLayout()
            choose = QPushButton("เลือก" + label)
            choose.clicked.connect(lambda checked=False, name=field: self.choose_file(name))
            row.addWidget(choose)
            self.controls.append(choose)
            if field in {"source_path", "vocab_path"}:
                button = QPushButton("เปิด")
                button.clicked.connect(lambda checked=False, name=field: self.open_selected(name))
                row.addWidget(button)
                self.controls.append(button)
            body.addLayout(row)
        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        body.addWidget(self.provider_label)
        settings = QPushButton("ตั้งค่า Provider / Model / API key")
        settings.clicked.connect(self.configure_provider)
        body.addWidget(settings)
        self.controls.append(settings)
        self.run_button = QPushButton("▶ หา + เกลา + อัปเดต")
        self.run_button.clicked.connect(self.start)
        body.addWidget(self.run_button)
        self.cancel_button = QPushButton("ยกเลิก")
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setVisible(False)
        body.addWidget(self.cancel_button)
        self.status = QLabel("พร้อมใช้งาน · บันทึกเนื้อหาก่อนกดเริ่ม")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        body.addStretch()
        self.body.setWidget(content)
        layout.addWidget(self.body)
        self.refresh(profile)

    def refresh(self, profile):
        self.profile = profile
        settings = profile.vocabulary_settings
        for field, label in self.labels.items():
            value = getattr(settings, field)
            label.setText(Path(value).name if value else "ยังไม่ได้เลือก")
            label.setToolTip(value)
        self.provider_label.setText(f"{settings.provider} · {settings.model or 'ยังไม่ได้ตั้ง model'}")
        self.body.setVisible(settings.panel_visible)
        self.toggle_button.setText("หาศัพท์ ‹" if settings.panel_visible else "ศัพท์ ›")
        self.setMinimumWidth(250 if settings.panel_visible else 42)
        self.setMaximumWidth(380 if settings.panel_visible else 70)

    def set_file(self, field, path):
        if field not in self.labels: raise ValueError("Unknown vocabulary file")
        setattr(self.profile.vocabulary_settings, field, str(Path(path).expanduser().resolve()))
        ProfileService.remember_browse_directory(self.repo, self.profile, path)
        self.repo.save_profile(self.profile)
        self.refresh(self.profile)

    def choose_file(self, field):
        filters = "Prompt (*.txt *.md *.json *.docx)" if "prompt" in field else (
            "VOCAB (*.tsv *.txt *.json)" if field == "vocab_path" else "เนื้อหา (*.txt *.md)")
        selected, _ = QFileDialog.getOpenFileName(self, "เลือกไฟล์", str(ProfileService.browse_directory(self.repo, self.profile)), filters)
        if selected: self.set_file(field, selected)

    def open_selected(self, field):
        path = getattr(self.profile.vocabulary_settings, field)
        if path: self.open_file(path)

    def toggle(self):
        settings = self.profile.vocabulary_settings
        settings.panel_visible = not settings.panel_visible
        self.repo.save_profile(self.profile)
        self.refresh(self.profile)

    def configure_provider(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("ตั้งค่า AI สำหรับนิยายเรื่องนี้")
        form = QFormLayout(dialog)
        settings = self.profile.vocabulary_settings
        provider = QComboBox()
        provider.addItems(["openai", "openai-compatible", "anthropic"])
        provider.setCurrentText(settings.provider)
        model, endpoint = QLineEdit(settings.model), QLineEdit(settings.base_url)
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("เว้นว่างเพื่อใช้ key ที่บันทึกไว้")
        delete = QCheckBox("ลบ key ของ provider ที่เลือก")
        form.addRow("Provider", provider)
        form.addRow("Model", model)
        form.addRow("API URL (HTTPS)", endpoint)
        form.addRow("API key", key)
        form.addRow(delete)
        notice = QLabel("API key เข้ารหัสด้วยบัญชี Windows นี้ · ส่งเนื้อหาและ VOCAB ไปยัง provider ที่เลือก")
        notice.setWordWrap(True)
        form.addRow(notice)
        provider.currentTextChanged.connect(lambda value: endpoint.setText(
            "https://api.anthropic.com/v1" if value == "anthropic" else "https://api.openai.com/v1"))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                selected = provider.currentText()
                create_provider(selected, endpoint.text().strip())
                if not model.text().strip(): raise ValueError("Model required")
                if delete.isChecked(): self.credentials.delete(self.profile.id, selected)
                elif key.text(): self.credentials.set(self.profile.id, selected, key.text().strip())
                settings.provider, settings.model, settings.base_url = selected, model.text().strip(), endpoint.text().strip()
                self.repo.save_profile(self.profile)
            except (ValueError, OSError):
                QMessageBox.warning(dialog, "บันทึกไม่ได้", "ตรวจ model, HTTPS URL และสิทธิ์เก็บ key ของ Windows")
                return
            finally: key.clear()
            self.refresh(self.profile)
            dialog.accept()
        buttons.accepted.connect(save)
        dialog.exec()
        key.clear()

    def start(self):
        if self.worker and self.worker.isRunning(): return
        settings = deepcopy(self.profile.vocabulary_settings)
        try:
            provider = create_provider(settings.provider, settings.base_url)
            key = self.credentials.get(self.profile.id, settings.provider)
            provider.validate_request(settings.model, key)
            if not settings.vocab_path: raise ValueError("Select VOCAB")
            if not self.prepare(settings.vocab_path): return
        except (ValueError, OSError):
            self.status.setText("เลือกไฟล์และตั้งค่า Provider / Model / API key ก่อนเริ่ม")
            return
        self.worker = VocabularyWorker(settings, provider, key, self)
        self.worker.phase.connect(lambda phase: self.status.setText(PHASES[phase]))
        self.worker.finished.connect(self.finished)
        self.run_button.setEnabled(False)
        for control in self.controls: control.setEnabled(False)
        self.cancel_button.setVisible(True)
        self.worker.start()

    def cancel(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.status.setText("กำลังยกเลิก รอคำตอบ API ปัจจุบัน…")

    def finished(self):
        worker = self.worker
        self.release(worker.settings.vocab_path)
        if worker.error: self.status.setText(worker.error)
        else:
            result = worker.result
            self.status.setText(f"✓ เสร็จแล้ว · เพิ่ม {result.added} · อัปเดต {result.updated}")
            self.status.setToolTip(f"Backup: {result.backup_path or 'ไม่มีการเปลี่ยนแปลง'}")
        for control in self.controls: control.setEnabled(True)
        self.run_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        worker.deleteLater()
        self.worker = None
