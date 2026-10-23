"""AI Web Workspace: persistent queue, assisted recovery, safe manual import."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QMessageBox,
    QCheckBox, QHeaderView, QInputDialog)

from .core import JobStore, build_jobs, record_response, ordered_results
from .browser import GeminiBrowserWorker
from novel_workflow.translation_batches import load_translation_source, validate_translation_source
from novel_workflow.translation_source_binding import (
    enabled_translation_attachments, source_candidates, translation_reference_files,
)


class AIWorkspacePage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("aiWorkspacePage")
        self.worker = None
        self.jobs = []
        self.store = None
        layout = QVBoxLayout(self)
        title = QLabel("AI Web Workspace · Gemini (Chrome)")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        hint = QLabel("เลือกนิยายและต้นฉบับที่ผูกไว้ · ตรวจงานก่อนส่ง · ส่งไม่แน่นอนให้แก้ใน Chrome โดยไม่ส่งซ้ำ")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        controls = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.setObjectName("aiWorkspaceProfile")
        self.profile.currentIndexChanged.connect(self._profile_changed)
        controls.addWidget(self.profile, 2)
        self.stage = QComboBox()
        self.stage.addItems(["แปล", "หาศัพท์", "เกลา"])
        controls.addWidget(self.stage)
        self.source = QComboBox()
        controls.addWidget(self.source, 2)
        layout.addLayout(controls)
        options = QHBoxLayout()
        self.size = QSpinBox()
        self.size.setRange(1, 30)
        self.size.setValue(3)
        self.tabs = QSpinBox()
        self.tabs.setRange(1, 10)
        self.tabs.setValue(10)
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.setPlaceholderText("โมเดลตามชื่อบนเว็บ Gemini")
        for label, widget in [("บท/งาน", self.size), ("สูงสุดแท็บ", self.tabs),
                              ("โมเดล (ตรวจบนเว็บ)", self.model)]:
            options.addWidget(QLabel(label))
            options.addWidget(widget)
        layout.addLayout(options)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Prompt เพิ่มเติม (ใช้ไฟล์ Prompt ที่ผูกกับขั้นตอนอยู่แล้วด้วย)")
        self.prompt.setMaximumHeight(90)
        layout.addWidget(self.prompt)
        actions = QHBoxLayout()
        for label, method in [("ตรวจและสร้างงาน", self.preview), ("เปิด Chrome / เริ่มส่ง", self.launch),
                              ("เปิดแท็บงาน", self.open_tab), ("รับผลด้วยตนเอง", self.manual_import),
                              ("ยืนยันส่งเองแล้ว", self.confirm_sent), ("ตรวจผลรวม", self.combine), ("Import / Export", self.import_export)]:
            button = QPushButton(label)
            button.clicked.connect(method)
            actions.addWidget(button)
        layout.addLayout(actions)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["งาน", "บท", "โมเดล", "สถานะ", "รายละเอียด"])
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, 1)
        self.status = QLabel("เลือกนิยายเพื่อเริ่ม")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.reload()

    def reload(self):
        current = self.profile.currentData()
        self.profile.blockSignals(True)
        self.profile.clear()
        for profile in self.owner.repo.list_profiles():
            self.profile.addItem(profile.name, profile.id)
        ix = self.profile.findData(current or (self.owner.profile.id if self.owner.profile else None))
        self.profile.setCurrentIndex(max(0, ix))
        self.profile.blockSignals(False)
        self._profile_changed()

    def _profile_changed(self, *_):
        pid = self.profile.currentData()
        self.source.clear()
        self.jobs = []
        self.store = JobStore(self.owner.repo.root, pid) if pid else None
        if self.store:
            try:
                self.jobs = self.store.load()
                self._source_entries = enabled_translation_attachments(
                    self.owner.repo, self.owner.assembler, self._selected_profile())
                for entry in source_candidates(self._source_entries):
                    self.source.addItem(entry.label, entry.id)
            except (OSError, ValueError, TypeError) as exc:
                self.status.setText(f"ตรวจไฟล์ผูกไว้ไม่ได้: {exc}")
        self._render()

    def _selected_profile(self):
        return next((p for p in self.owner.repo.list_profiles()
                     if p.id == self.profile.currentData()), None)

    def _save(self):
        if self.store:
            self.store.save(self.jobs)
        self._render()

    def _render(self):
        ordered = sorted(self.jobs, key=lambda j: (j.batch_id, j.submission_order))
        self.table.setRowCount(len(ordered))
        for i, job in enumerate(ordered):
            fields = [str(job.submission_order), ",".join(map(str, job.chapter_numbers)),
                      job.model, job.status, job.error]
            for col, value in enumerate(fields):
                self.table.setItem(i, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()

    def _chosen(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        shown = sorted(self.jobs, key=lambda j: (j.batch_id, j.submission_order))
        return shown[row] if row < len(shown) else None

    def preview(self):
        profile = self._selected_profile()
        entry = next((e for e in getattr(self, "_source_entries", ())
                      if e.id == self.source.currentData()), None)
        if not profile or entry is None or not entry.path:
            self.status.setText("ไม่พบต้นฉบับที่ผูกไว้ กรุณาตรวจขั้นตอนแปล")
            return
        try:
            source = load_translation_source("step", path=entry.path)
            refs = translation_reference_files(self._source_entries, entry.path, entry.id)
            validate_translation_source(source)
            jobs = build_jobs(profile.id, self.stage.currentText(), source.chapters,
                              self.size.value(), max_tabs=self.tabs.value(),
                              references=refs, model=self.model.currentText().strip(),
                              prompt=self.prompt.toPlainText())
            if self.jobs and any(j.status not in {"IMPORTED", "CANCELLED"} for j in self.jobs):
                raise ValueError("มีงานเดิมที่ยังไม่จบ กรุณานำผลลัพธ์ออกก่อนสร้างงานใหม่")
            self.jobs = jobs
            self._save()
            self.status.setText(f"เตรียม {len(jobs)} งาน / {len(source.chapters)} บท · ยังไม่ส่ง")
        except (OSError, ValueError) as exc:
            self.status.setText(f"สร้างงานไม่ได้: {exc}")

    def launch(self):
        if self.worker and self.worker.isRunning():
            self.status.setText("Chrome Workspace ทำงานอยู่แล้ว")
            return
        waiting = [j for j in self.jobs if j.status == "PREPARED"]
        if not waiting:
            self.status.setText("ไม่มีงานที่เตรียมไว้ หรือกำลังรอแก้ไขงานเดิม")
            return
        if not all(j.model and j.prompt.strip() for j in waiting):
            self.status.setText("กรอกชื่อโมเดลและ Prompt ก่อนเริ่ม · โปรแกรมจะไม่ส่งข้อความว่าง")
            return
        entries = []
        try:
            for job in waiting:
                attachments = [*job.source_files, *job.reference_files]
                if not all(p and Path(p).is_file() for p in attachments):
                    raise ValueError(f"งาน {job.submission_order} มีไฟล์ต้นฉบับไม่พร้อม")
                entries.append({**vars(job), "attachments": attachments})
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.worker = GeminiBrowserWorker(entries, self.owner.repo.root / "chrome-ai-profile", parent=self)
        self.worker.event.connect(self._event)
        self.worker.diagnostic.connect(self.status.setText)
        self.worker.finished.connect(lambda: self.status.setText("Chrome หยุดทำงาน · ตรวจสถานะงานได้"))
        self.worker.start()
        self.status.setText("กำลังเปิด Google Chrome · บัญชี Google ต้องเข้าสู่ระบบด้วยตนเอง")

    def _event(self, job_id, state, reason, url):
        job = next((j for j in self.jobs if j.job_id == job_id), None)
        if not job:
            return
        if state.startswith("RAW:"):
            record_response(job, state[4:])
        else:
            job.status = state
            job.error = reason
            if state == "SUBMITTED":
                job.submitted_verified = True
            if url:
                job.page_url = url
        self._save()
        self.status.setText(f"งาน {job.submission_order}: {job.status} {job.error}")

    def open_tab(self):
        job = self._chosen()
        if job and self.worker and self.worker.isRunning():
            self.worker.enqueue("open", job.job_id)
            self.status.setText(f"สั่งเปิดแท็บงาน {job.submission_order}")
        else:
            self.status.setText("กรุณาเลือกงานที่มี Chrome กำลังเปิดอยู่")

    def confirm_sent(self):
        job = self._chosen()
        if not job:
            self.status.setText("เลือกงานก่อน")
            return
        confirm = QMessageBox.question(self, "ยืนยันส่งงานเอง",
            f"คุณเห็นข้อความที่ส่งแล้วจริงบน Gemini สำหรับงาน {job.submission_order} ใช่หรือไม่?")
        if confirm == QMessageBox.Yes:
            job.status, job.submitted_verified = "SUBMITTED", True
            self._save()
            if self.worker and self.worker.isRunning():
                self.worker.enqueue("sent", job.job_id)

    def manual_import(self):
        job = self._chosen()
        if not job:
            self.status.setText("เลือกงานก่อน")
            return
        text, ok = QInputDialog.getMultiLineText(self, f"รับคำตอบดิบงาน {job.submission_order}",
                                                   "วางข้อความทั้งหมดจาก Gemini:", job.raw_response)
        if ok and text.strip():
            try:
                record_response(job, text)
                self._save()
                self.status.setText(f"รับผลลัพธ์งาน {job.submission_order}: {job.status}")
            except ValueError as exc:
                self.status.setText(str(exc))

    def combine(self):
        try:
            text = ordered_results(self.jobs)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        QApplication = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
        QApplication.clipboard().setText(text)
        self.status.setText("ตรวจครบแล้ว · คัดลอกผลรวมลง Clipboard เพื่อวางใน Translator และ Export ผ่านขั้นตอนเดิม")


    def import_export(self):
        """Use existing Translator export only, with preflight and user confirmation."""
        try:
            text = ordered_results(self.jobs)
            profile = self._selected_profile()
            if not profile or not self.owner.profile or self.owner.profile.id != profile.id:
                raise ValueError("กรุณาเปิดนิยายเรื่องนี้ใน Workspace ก่อน")
            if any(job.stage != "แปล" for job in self.jobs):
                raise ValueError("Import Translator รองรับเฉพาะขั้นตอนแปล")
            if all(job.imported for job in self.jobs):
                raise ValueError("ชุดงานนี้นำเข้าและ Export แล้ว")
            workspace = self.owner.workspaces.get(profile.id)
            if workspace is None:
                raise ValueError("ไม่พบ Workspace ของนิยาย")
            candidates = [path for path in self.owner._profile_file_paths(profile)
                          if path.name.casefold().endswith("translator.txt")
                          and path.name.casefold() != "translator.txt"
                          and self.owner._translator_profile_for_path(profile.id, path)]
            if len(candidates) != 1:
                raise ValueError("Translator ที่ผูกกับนิยายไม่ชัดเจน")
            target = candidates[0]
            if target.read_bytes().strip():
                raise ValueError("Translator มีข้อมูลอยู่แล้ว · กรุณา Export งานเดิมก่อน")
            if not workspace.editor.save_all(include_normalization=False):
                raise ValueError("มีงานที่ยังบันทึกไม่สำเร็จ")
            if not workspace.editor.open_file(target):
                raise ValueError("ไม่สามารถเปิด Translator")
            editor = workspace.editor._current_editor()
            if workspace.editor._path(editor) != target or workspace.editor._dirty(editor):
                raise ValueError("Translator มีการแก้ไขค้างอยู่")
            if target.read_bytes().strip():
                raise ValueError("Translator ถูกแก้ไขจากภายนอก")
            confirmation = QMessageBox.question(
                self, "ยืนยัน Import + Export",
                f"นำเข้า {sum(len(j.chapter_numbers) for j in self.jobs)} บท"
                " ลง Translator ที่ว่าง และ Export ด้วยระบบเดิมหรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirmation != QMessageBox.Yes:
                return
            editor.setPlainText(text)
            if not workspace.editor.save_editor(editor, quiet=True, normalize=False):
                raise ValueError("บันทึก Translator ไม่สำเร็จหรือมีการแก้ไขจากภายนอก")
            # The existing Export handles backup, Context, progress, history and
            # recovery journal. Its confirmation and preflight remain enabled.
            if not self.owner.update_context_from_translator(workspace):
                self.status.setText("นำเข้าแล้ว แต่ Export ยังไม่สำเร็จ · ผลลัพธ์ถูกเก็บไว้")
                return
            for job in self.jobs:
                job.imported = True
                job.status = "IMPORTED"
            self._save()
            self.status.setText("Import/Export สำเร็จผ่าน Workflow เดิม")
        except (ValueError, TypeError, OSError) as exc:
            self.status.setText(f"Import/Export ไม่สำเร็จ: {exc}")

    def shutdown(self):
        if self.worker and self.worker.isRunning():
            self.worker.enqueue("stop")
