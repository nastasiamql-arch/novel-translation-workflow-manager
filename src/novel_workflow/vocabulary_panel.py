"""Per-novel panel and cancellable background pipeline."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFileDialog, QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox,
    QCheckBox, QScrollArea)

from .credentials import CredentialStore
from .providers import create_provider, connect_and_list_models
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
        self.current_phase = "snapshot"

    def _failure_message(self, error):
        phase = self.current_phase
        provider_hint = None
        if isinstance(error, ValueError):
            message = str(error)
            if message.startswith("Provider HTTP "):
                code = message.split()[2].rstrip(";")
                labels = {401: "API key ไม่ถูกต้อง", 403: "key ไม่มีสิทธิ์ใช้ Pool/API นี้",
                          404: "ไม่พบ endpoint หรือ model", 429: "โควตาหรือ rate limit เต็ม"}
                try: provider_hint = f"API ตอบ HTTP {code} · {labels.get(int(code), 'ตรวจสิทธิ์หรือสถานะ API')}"
                except ValueError: provider_hint = "API ปฏิเสธคำขอ ตรวจสิทธิ์และสถานะ API"
            else:
                safe_hints = {
                    "Provider connection failed or timed out": "เชื่อม API ไม่ได้หรือหมดเวลารอ",
                    "Provider returned invalid JSON": "API ส่งคำตอบที่ไม่ใช่ JSON",
                    "Provider response is incomplete or refused": "API ตอบไม่ครบหรือปฏิเสธคำขอ",
                    "Provider returned empty content": "API ส่งคำตอบว่าง",
                    "Unexpected provider response": "รูปแบบคำตอบจาก API ไม่ตรงที่รองรับ",
                }
                provider_hint = safe_hints.get(message)

        if phase in {"extract", "polish"}:
            step = "หาศัพท์" if phase == "extract" else "เกลาศัพท์"
            return f"ขั้น{step}ไม่สำเร็จ · {provider_hint or 'ตรวจสิทธิ์ API, ชื่อ model และคำตอบจาก AI'}"
        if phase == "snapshot":
            return "อ่านไฟล์ไม่สำเร็จ · ตรวจไฟล์เนื้อหา, VOCAB และ Prompt ว่ายังเปิดได้และรูปแบบถูกต้อง"
        if phase == "validate":
            return "ตรวจผล AI ไม่ผ่าน · ผลต้องเป็น JSON NEW/UPDATE และแต่ละแถวต้องตรงคอลัมน์ VOCAB"
        if phase == "backup":
            return "สำรอง VOCAB ไม่สำเร็จ · ตรวจสิทธิ์เขียนโฟลเดอร์ที่เก็บ VOCAB"
        if phase == "commit":
            return "อัปเดต VOCAB ไม่สำเร็จ · ตรวจสิทธิ์เขียนไฟล์; backup ต้นฉบับยังคงอยู่"
        return "ทำงาน VOCAB ไม่สำเร็จ · ตรวจไฟล์และการตั้งค่า แล้วลองใหม่"

    def run(self):
        try:
            def set_phase(phase):
                self.current_phase = phase
                self.phase.emit(phase)
            self.result = run_vocabulary(self.settings, self.provider, self.key,
                progress=set_phase, cancelled=self.isInterruptionRequested)
        except Cancelled:
            self.error = "ยกเลิกแล้ว"
        except (ValueError, OSError, UnicodeError) as error:
            # Show only phase/category and allowlisted API errors; never include user data or credentials.
            self.error = self._failure_message(error)
        except Exception:
            self.error = self._failure_message(RuntimeError())
        finally:
            self.key = ""


class ModelListWorker(QThread):
    succeeded = Signal(str, list)
    failed = Signal(str)

    def __init__(self, provider, key, parent=None):
        super().__init__(parent)
        self.provider, self.key = provider, key

    def run(self):
        try:
            endpoint, models = connect_and_list_models(self.provider, self.key)
            self.succeeded.emit(endpoint, models)
        except ValueError as error:
            self.failed.emit(str(error))
        except Exception:
            self.failed.emit("เชื่อมต่อไม่ได้ ตรวจ URL, API key และสิทธิ์ดูรายการโมเดล")
        finally:
            self.key = ""


class ProviderDialog(QDialog):
    """Keep controls alive while an in-flight model request finishes."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model_worker = None

    def reject(self):
        if self.model_worker and self.model_worker.isRunning(): return
        super().reject()

    def closeEvent(self, event):
        if self.model_worker and self.model_worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)


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
        dialog = ProviderDialog(self)
        dialog.setWindowTitle("ตั้งค่า AI สำหรับนิยายเรื่องนี้")
        form = QFormLayout(dialog)
        settings = self.profile.vocabulary_settings
        provider = QComboBox()
        provider.addItems(["openai", "openai-compatible", "anthropic"])
        provider.setCurrentText(settings.provider)
        model, endpoint = QComboBox(), QLineEdit(settings.base_url)
        model.setEditable(True)
        model.setInsertPolicy(QComboBox.NoInsert)
        model.setCurrentText(settings.model)
        key = QLineEdit()
        key.setEchoMode(QLineEdit.Password)
        key.setPlaceholderText("เว้นว่างเพื่อใช้ key ที่บันทึกไว้")
        delete = QCheckBox("ลบ key ของ provider ที่เลือก")
        form.addRow("Provider", provider)
        form.addRow("Model", model)
        form.addRow("API URL (HTTPS)", endpoint)
        form.addRow("API key", key)
        connect_row = QHBoxLayout()
        connect_button = QPushButton("เชื่อมต่อและดึงรายการโมเดล")
        connection_status = QLabel("")
        connection_status.setWordWrap(True)
        connect_row.addWidget(connect_button)
        form.addRow(connect_row)
        form.addRow(connection_status)
        form.addRow(delete)
        notice = QLabel("API key เข้ารหัสด้วยบัญชี Windows นี้ · ส่งเนื้อหาและ VOCAB ไปยัง provider ที่เลือก")
        notice.setWordWrap(True)
        form.addRow(notice)
        provider.currentTextChanged.connect(lambda value: endpoint.setText(
            "https://api.anthropic.com/v1" if value == "anthropic" else "https://api.openai.com/v1"))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        form.addRow(buttons)
        buttons.rejected.connect(dialog.reject)

        def fetch_models():
            try:
                selected = provider.currentText()
                api = create_provider(selected, endpoint.text().strip())
                credential = key.text().strip() or self.credentials.get(self.profile.id, selected)
                api.validate_request("model-list", credential)
            except (ValueError, OSError):
                connection_status.setText("ตรวจ URL แบบ HTTPS และ API key ก่อนเชื่อมต่อ")
                return
            connect_button.setEnabled(False)
            buttons.button(QDialogButtonBox.Save).setEnabled(False)
            connection_status.setText("กำลังเชื่อมต่อและอ่านรายการโมเดล…")
            worker = ModelListWorker(api, credential, dialog)
            dialog.model_worker = worker
            def succeeded(resolved_endpoint, names):
                previous = model.currentText().strip()
                model.clear()
                model.addItems(names)
                model.setCurrentText(previous if previous in names else names[0])
                endpoint.setText(resolved_endpoint)
                pool = resolved_endpoint.removeprefix("https://api.maxplus-ai.cc") or "Native"
                connection_status.setText(f"เชื่อมต่อสำเร็จ · {pool} · พบ {len(names)} โมเดล")
            def failed(message):
                connection_status.setText(message)
            def finished():
                connect_button.setEnabled(True)
                buttons.button(QDialogButtonBox.Save).setEnabled(True)
                dialog.model_worker = None
                worker.deleteLater()
            worker.succeeded.connect(succeeded)
            worker.failed.connect(failed)
            worker.finished.connect(finished)
            worker.start()

        connect_button.clicked.connect(fetch_models)
        def save():
            try:
                selected = provider.currentText()
                create_provider(selected, endpoint.text().strip())
                if not model.currentText().strip(): raise ValueError("Model required")
                if delete.isChecked(): self.credentials.delete(self.profile.id, selected)
                elif key.text(): self.credentials.set(self.profile.id, selected, key.text().strip())
                settings.provider, settings.model, settings.base_url = selected, model.currentText().strip(), endpoint.text().strip()
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
