"""AI Web Workspace: persistent queue, assisted recovery, safe manual import."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem, QTextEdit, QMessageBox,
    QCheckBox, QHeaderView, QInputDialog)

from .core import JobStore, build_jobs, record_response, ordered_results, now
from .browser import GeminiBrowserWorker
from novel_workflow.translation_batches import load_translation_source, validate_translation_source
from novel_workflow.translation_batch_clipboard import prepare_translation_batch
from novel_workflow.vocabulary_batches import ChapterBatch, ChapterFile
from .bindings import stage_attachments
from novel_workflow.translation_source_binding import (
    enabled_translation_attachments, source_candidates, translation_reference_files,
)


class BundlePreparationWorker(QThread):
    prepared = Signal(object)
    failed = Signal(str)

    def __init__(self, source, jobs, references, directory, *, as_zip=False):
        super().__init__()
        self.source = source
        self.jobs = jobs
        self.references = references
        self.directory = directory
        self.as_zip = as_zip

    def run(self):
        try:
            chapters = {ch.number: ch for ch in self.source.chapters}
            outputs = {}
            for job in self.jobs:
                if self.isInterruptionRequested():
                    return
                selected = tuple(ChapterFile(n, chapters[n].path or Path(chapters[n].filename))
                                 for n in job.chapter_numbers)
                group = ChapterBatch(job.submission_order, job.chapter_numbers[0],
                                     job.chapter_numbers[-1], selected, ())
                prepared = prepare_translation_batch(
                    self.source, group, self.references,
                    self.directory / job.batch_id / job.job_id,
                    as_zip=self.as_zip)
                outputs[job.job_id] = [str(path) for path in prepared]
            self.prepared.emit(outputs)
        except (OSError, ValueError, UnicodeError) as exc:
            self.failed.emit(str(exc))


class AIWorkspacePage(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setObjectName("aiWorkspacePage")
        self.worker = None
        self.prepare_worker = None
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
        self.stage.currentIndexChanged.connect(self._stage_changed)
        controls.addWidget(self.stage)
        self.source = QComboBox()
        controls.addWidget(self.source, 2)
        layout.addLayout(controls)
        options = QHBoxLayout()
        self.size = QSpinBox()
        self.size.setRange(1, 100)
        self.size.setValue(3)
        self.tabs = QSpinBox()
        self.tabs.setRange(1, 10)
        self.tabs.setValue(10)
        self.range_start = QSpinBox()
        self.range_end = QSpinBox()
        for spin in (self.range_start, self.range_end):
            spin.setRange(0, 1000000)
            spin.setSpecialValueText("ทั้งหมด")
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0.1, 10.0)
        self.gap.setSingleStep(0.1)
        self.gap.setValue(1.0)
        self.gap.setSuffix(" วินาที")
        self.model = QComboBox()
        self.model.setEditable(True)
        self.model.setInsertPolicy(QComboBox.NoInsert)
        self.model.setPlaceholderText("โมเดลตามชื่อบนเว็บ Gemini")
        for label, widget in [("เริ่มบท", self.range_start), ("ถึงบท", self.range_end),
                              ("บท/งาน", self.size), ("สูงสุดแท็บ", self.tabs),
                              ("จังหวะส่ง", self.gap), ("โมเดล", self.model)]:
            options.addWidget(QLabel(label))
            options.addWidget(widget)
        self.zip_mode = QCheckBox("แนบเป็น ZIP")
        options.addWidget(self.zip_mode)
        layout.addLayout(options)
        self.prompt = QTextEdit()
        self.prompt.setPlaceholderText("Prompt เพิ่มเติม (ใช้ไฟล์ Prompt ที่ผูกกับขั้นตอนอยู่แล้วด้วย)")
        self.prompt.setMaximumHeight(90)
        layout.addWidget(self.prompt)
        action_groups = [
            [("ตรวจและสร้างงาน", self.preview), ("เปิด Chrome / เริ่มส่ง", self.launch),
             ("เปิดแท็บงาน", self.open_tab), ("หยุด Chrome Workspace", self.stop_worker),
             ("ตรวจสถานะอีกครั้ง", self.retry_job),
             ("ยืนยันส่งเองแล้ว", self.confirm_sent), ("ยกเลิกงาน", self.cancel_job)],
            [("รับผลอีกครั้ง", self.collect_again), ("รับผลด้วยตนเอง", self.manual_import),
             ("ตรวจผลรวม", self.combine), ("เปลี่ยนโมเดลงาน", self.edit_model),
             ("Import / Export", self.import_export)],
        ]
        for group in action_groups:
            actions = QHBoxLayout()
            for label, method in group:
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
                self._stage_changed()
            except (OSError, ValueError, TypeError) as exc:
                self.status.setText(f"ตรวจไฟล์ผูกไว้ไม่ได้: {exc}")
        self._render()

    def _stage_changed(self, *_):
        current = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        try:
            self._source_entries = stage_attachments(
                self.owner.repo, self.owner.assembler, self._selected_profile(),
                self.stage.currentText())
            for entry in source_candidates(self._source_entries):
                self.source.addItem(entry.label, entry.id)
            selected = self.source.findData(current)
            if selected >= 0:
                self.source.setCurrentIndex(selected)
        except (OSError, ValueError, TypeError) as exc:
            self._source_entries = ()
            self.status.setText(f"ตรวจไฟล์ที่ผูกไว้ไม่ได้: {exc}")
        finally:
            self.source.blockSignals(False)

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
        if self.prepare_worker is not None and self.prepare_worker.isRunning():
            self.status.setText("กำลังเตรียมไฟล์อยู่ กรุณารอให้ตรวจครบก่อน")
            return
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
            first = self.range_start.value() or source.chapters[0].number
            last = self.range_end.value() or source.chapters[-1].number
            selected_chapters = [ch for ch in source.chapters if first <= ch.number <= last]
            if first > last or not selected_chapters or selected_chapters[0].number != first or selected_chapters[-1].number != last:
                raise ValueError("ช่วงบทไม่พบในต้นฉบับหรือระบุช่วงผิด")
            jobs = build_jobs(profile.id, self.stage.currentText(), selected_chapters,
                              self.size.value(), max_tabs=self.tabs.value(),
                              references=refs, model=self.model.currentText().strip(),
                              prompt=self.prompt.toPlainText().strip() or (
                                  "ปฏิบัติตามไฟล์ Prompt ที่แนบ และใช้ไฟล์อ้างอิงทั้งหมด"
                                  if any(any(term in path.name.lower() for term in
                                    ("prompt", "คำสั่ง", "提示")) for path in refs) else ""))
            if self.jobs and any(j.status not in {"IMPORTED", "CANCELLED"} for j in self.jobs):
                raise ValueError("มีงานเดิมที่ยังไม่จบ กรุณานำผลลัพธ์ออกก่อนสร้างงานใหม่")
            worker = BundlePreparationWorker(
                source, jobs, refs, self.owner.repo.root / "cache" / "ai_workspace" / profile.id,
                as_zip=self.zip_mode.isChecked())
            self.prepare_worker = worker
            self.status.setText(f"กำลังตรวจและจัดชุดไฟล์ {len(jobs)} งาน โดยไม่หยุด UI…")
            def prepared(results):
                for job in jobs:
                    job.prepared_files = results[job.job_id]
                self.jobs = jobs
                self._save()
                self.status.setText(
                    f"ตรวจและเตรียมไฟล์ครบ {len(jobs)} งาน / {len(source.chapters)} บท · ยังไม่ส่ง")
            worker.prepared.connect(prepared)
            worker.failed.connect(lambda detail: self.status.setText(f"เตรียมไฟล์ไม่สำเร็จ: {detail}"))
            worker.finished.connect(lambda: setattr(self, 'prepare_worker', None))
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except (OSError, ValueError) as exc:
            self.status.setText(f"สร้างงานไม่ได้: {exc}")

    def launch(self):
        if self.prepare_worker and self.prepare_worker.isRunning():
            self.status.setText("ต้องตรวจไฟล์ครบก่อนเริ่ม Chrome")
            return
        if self.worker and self.worker.isRunning():
            self.status.setText("Chrome Workspace ทำงานอยู่แล้ว")
            return
        waiting = [j for j in self.jobs if j.status in {
            "PREPARED", "OPENED", "MODEL_SELECTED", "READY",
            "GOOGLE_LOGIN_REQUIRED", "MODEL_NOT_FOUND", "MODEL_SELECTION_FAILED",
            "ATTACHMENT_NOT_READY", "ATTACHMENT_UPLOAD_FAILED", "ATTACHMENT_TIMEOUT",
            "ATTACHMENT_FAILED", "UPLOADING", "CHECKING_ATTACHMENTS",
            "ATTACHMENT_READY", "READY_TO_SEND", "PROMPT_INSERT_FAILED"}]
        if not waiting:
            self.status.setText("ไม่มีงานที่เตรียมไว้ หรือกำลังรอแก้ไขงานเดิม")
            return
        if not all(j.model and j.prompt.strip() for j in waiting):
            self.status.setText("กรอกชื่อโมเดลและ Prompt ก่อนเริ่ม · โปรแกรมจะไม่ส่งข้อความว่าง")
            return
        entries = []
        try:
            for job in waiting:
                attachments = job.prepared_files
                if not all(p and Path(p).is_file() for p in attachments):
                    raise ValueError(f"งาน {job.submission_order} มีไฟล์ต้นฉบับไม่พร้อม")
                entries.append({**vars(job), "attachments": attachments})
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.worker = GeminiBrowserWorker(entries, self.owner.repo.root / "chrome-ai-profile",
                                          send_gap=self.gap.value(), parent=self)
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
        if state == "SUBMITTED":
            job.submitted_at = now()
        if state == "READY_TO_SEND":
            job.error = ""
        job.events.append({"time": now(), "status": job.status, "detail": (job.error or "")[:180]})
        self._save()
        self.status.setText(f"งาน {job.submission_order}: {job.status} {job.error}")

    def stop_worker(self):
        if self.worker and self.worker.isRunning():
            self.worker.enqueue("stop")
            self.status.setText("กำลังหยุดการควบคุม Chrome โดยรักษาข้อมูลงานไว้")
        else:
            self.status.setText("ไม่มี Chrome Workspace ที่กำลังทำงาน")

    def open_tab(self):
        job = self._chosen()
        if job and self.worker and self.worker.isRunning():
            self.worker.enqueue("open", job.job_id)
            self.status.setText(f"สั่งเปิดแท็บงาน {job.submission_order}")
        else:
            self.status.setText("กรุณาเลือกงานที่มี Chrome กำลังเปิดอยู่")

    def retry_job(self):
        job = self._chosen()
        if not job:
            self.status.setText("กรุณาเลือกงาน")
            return
        if job.status == "SEND_UNCONFIRMED" or job.submitted_verified or job.imported:
            self.status.setText("งานนี้อาจถูกส่งแล้ว ห้ามส่งซ้ำ · ตรวจแท็บหรือยืนยันส่งเอง")
            return
        if self.worker is None or not self.worker.isRunning():
            self.status.setText("Chrome ไม่ได้เปิดอยู่ · ใช้เปิด Chrome / เริ่มส่งเพื่อกู้คืน")
            return
        self.worker.enqueue("retry", job.job_id)
        self.status.setText(f"กำลังตรวจไฟล์และโมเดลใหม่สำหรับงาน {job.submission_order}")

    def collect_again(self):
        job = self._chosen()
        if job and self.worker and self.worker.isRunning() and job.submitted_verified:
            self.worker.enqueue("collect", job.job_id)
            self.status.setText(f"กำลังรับผลเดิมของงาน {job.submission_order} อีกครั้ง")
        else:
            self.status.setText("เลือกงานที่ยืนยันการส่งแล้วและมี Chrome เปิดอยู่")

    def cancel_job(self):
        job = self._chosen()
        if not job:
            self.status.setText("เลือกงานก่อน")
            return
        if job.submitted_verified or job.raw_response:
            self.status.setText("งานส่งแล้วหรือมีผลลัพธ์ · ไม่ยกเลิกทับข้อมูลที่รับมา")
            return
        if QMessageBox.question(self, "ยกเลิกงาน",
                f"ยกเลิกงาน {job.submission_order} โดยเก็บข้อมูลต้นฉบับไว้ใช่หรือไม่?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            if self.worker and self.worker.isRunning():
                self.worker.enqueue("cancel", job.job_id)
            job.status = "CANCELLED"
            self._save()

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

    def edit_model(self):
        job = self._chosen()
        if job is None:
            self.status.setText("เลือกงานก่อน")
            return
        if job.submitted_verified or job.raw_response:
            self.status.setText("งานนี้ส่งหรือรับคำตอบแล้ว ห้ามเปลี่ยนโมเดลย้อนหลัง")
            return
        value, ok = QInputDialog.getText(self, "โมเดลงาน", "ชื่อโมเดลตามตัวเลือก Gemini:", text=job.model)
        if ok and value.strip():
            job.model = value.strip()
            self._save()
            self.status.setText(f"กำหนดโมเดลให้งาน {job.submission_order} แล้ว · ระบบจะตรวจจริงก่อนแนบไฟล์")

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
        if self.prepare_worker and self.prepare_worker.isRunning():
            self.prepare_worker.requestInterruption()
        if self.worker and self.worker.isRunning():
            self.worker.enqueue("stop")
