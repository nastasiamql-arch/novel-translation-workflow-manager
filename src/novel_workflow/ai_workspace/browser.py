"""Conservative Chrome/Gemini adapter. Browser objects never cross the worker thread.

Google's website is not a public automation API. When its DOM cannot prove a
condition, stop that job for assisted recovery instead of guessing or resending.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from queue import Empty, Queue
import re
import time

from PySide6.QtCore import QThread, Signal


class BrowserFailure(Exception):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


class GeminiBrowserWorker(QThread):
    event = Signal(str, str, str, str)  # job id, state, reason, url
    diagnostic = Signal(str)

    def __init__(self, jobs, profile_directory: Path, *, send_gap=1.0, parent=None):
        super().__init__(parent)
        self.jobs = [dict(job) for job in jobs]
        self.profile_directory = Path(profile_directory)
        self.send_gap = max(0.0, float(send_gap))
        self.commands = Queue()
        self._stop_requested = False

    def enqueue(self, operation: str, job_id=""):
        self.commands.put((operation, job_id))

    def _emit(self, job, state, detail=""):
        self.event.emit(job["job_id"], state, detail, getattr(job.get("page"), "url", ""))

    def _selector(self, page, role, *names):
        for name in names:
            locator = page.get_by_role(role, name=re.compile(name, re.I))
            if locator.count() == 1:
                return locator
        return None

    def _select_model(self, page, job):
        model = job.get("model", "").strip()
        if not model:
            raise BrowserFailure("MODEL_NOT_FOUND", "ยังไม่ได้เลือกโมเดล: เปิดแท็บและเลือกโมเดลก่อนแนบไฟล์")
        control = self._selector(page, "button", r"model|โมเดล|fast|pro|thinking")
        if control is None:
            raise BrowserFailure("MODEL_SELECTION_FAILED", "ไม่พบตัวเลือกโมเดลที่ยืนยันได้")
        control.click(timeout=5000)
        option = page.get_by_text(model, exact=True)
        if option.count() != 1:
            raise BrowserFailure("MODEL_NOT_FOUND", f"ไม่มีโมเดล {model} ให้เลือกในหน้าเว็บ")
        option.click(timeout=5000)
        # Verify the selection is represented by a visible button, not just a click.
        if not page.get_by_role("button", name=re.compile(re.escape(model), re.I)).count():
            raise BrowserFailure("MODEL_SELECTION_FAILED", f"ยืนยันโมเดล {model} ไม่ได้")
        self._emit(job, "MODEL_SELECTED", model)

    def _prepare(self, job):
        page = job["page"]
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=25000)
        if "accounts.google.com" in page.url:
            raise BrowserFailure("GOOGLE_LOGIN_REQUIRED", "Google ขอเข้าสู่ระบบด้วยตนเอง")
        self._select_model(page, job)
        attachments = [Path(p) for p in job.get("attachments", [])]
        if not attachments or any(not p.is_file() for p in attachments):
            raise BrowserFailure("ATTACHMENT_NOT_FOUND", "ไฟล์ต้นฉบับ/ไฟล์ประกอบไม่ครบ")
        for path in attachments:
            if path.stat().st_size == 0:
                raise BrowserFailure("ATTACHMENT_NOT_FOUND", f"ไฟล์ว่าง: {path.name}")
        file_input = page.locator('input[type="file"]')
        if file_input.count() != 1:
            attach = self._selector(page, "button", r"attach|upload|แนบ|อัปโหลด|เพิ่มไฟล์")
            if attach is None:
                raise BrowserFailure("ATTACHMENT_UPLOAD_FAILED", "ไม่พบวิธีแนบไฟล์บน Gemini")
            attach.click(timeout=4000)
            file_input = page.locator('input[type="file"]')
        if file_input.count() != 1:
            raise BrowserFailure("ATTACHMENT_UPLOAD_FAILED", "ตัวรับไฟล์ไม่ชัดเจน กรุณาแนบเอง")
        file_input.set_input_files([str(p) for p in attachments], timeout=12000)
        composer = page.locator('[contenteditable="true"]')
        if composer.count() != 1:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ไม่พบช่องพิมพ์ Prompt ที่ระบุแน่นอน")
        prompt = job.get("prompt", "").strip()
        if not prompt:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ไม่มี Prompt กรุณากรอกด้วยตนเอง")
        composer.fill(prompt, timeout=6000)
        if composer.inner_text().strip() != prompt:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ตรวจสอบข้อความ Prompt ไม่ตรง")
        if not self._attachments_ready(page, [p.name for p in attachments]):
            raise BrowserFailure("ATTACHMENT_NOT_READY", "ยังยืนยันไฟล์แนบครบทุกไฟล์ไม่ได้ กรุณาตรวจบน Chrome")
        self._emit(job, "READY", f"ตรวจ {len(attachments)} ไฟล์")
        return True

    @staticmethod
    def _attachments_ready(page, filenames):
        """Fail closed on virtualized/opaque attachment UI; never rely on a fixed delay."""
        return bool(page.evaluate(r"""(names) => {
          const root = document.querySelector('input[type=file]')?.closest('form')
                    || document.querySelector('[contenteditable=true]')?.parentElement?.parentElement;
          if (!root) return false;
          const nodes = Array.from(root.querySelectorAll('[aria-label], [title], [data-file-name]'));
          return names.every(name => {
            const hits = nodes.filter(el => [el.getAttribute('aria-label'), el.getAttribute('title'),
                el.getAttribute('data-file-name')].some(value => value && value.includes(name)));
            return hits.length === 1 && hits.every(el => {
              const text = [el.getAttribute('aria-label'), el.getAttribute('title'),
                  el.getAttribute('data-state')].join(' ').toLowerCase();
              if (/loading|uploading|progress|error|failed|กำลัง|ผิดพลาด/.test(text)) return false;
              const busy = el.matches('[aria-busy=true], [role=progressbar]') ||
                !!el.querySelector('[aria-busy=true], [role=progressbar], progress');
              return !busy;
            });
          });
        }""", filenames))

    def _send(self, job):
        page = job["page"]
        expected = [Path(p).name for p in job["attachments"]]
        if not self._attachments_ready(page, expected):
            raise BrowserFailure("ATTACHMENT_NOT_READY", "ไฟล์ยังไม่พร้อม ห้ามส่งอัตโนมัติ")
        send = self._selector(page, "button", r"send|ส่ง")
        if send is None or not send.is_enabled():
            raise BrowserFailure("SEND_BUTTON_UNAVAILABLE", "ปุ่มส่งยังไม่พร้อม")
        # A click is not proof of acceptance; unconfirmed prompts must not be retried.
        send.click(timeout=5000)
        self._emit(job, "SEND_UNCONFIRMED", "กดส่งแล้ว กำลังตรวจหลักฐาน")
        # Conversation user messages can be virtualized or hidden; never infer from time.
        try:
            page.get_by_role("main").get_by_text(job["prompt"], exact=True).wait_for(
                state="visible", timeout=9000)
        except Exception:
            raise BrowserFailure("SEND_UNCONFIRMED", "ไม่สามารถยืนยันการรับ Prompt ห้ามกดซ้ำอัตโนมัติ")
        job["sent"] = True
        self._emit(job, "SUBMITTED", "เว็บไซต์แสดงข้อความที่ส่งแล้ว")

    def _collect(self, job):
        page = job["page"]
        responses = page.locator("model-response")
        if not responses.count():
            return False
        last = responses.last
        stop = self._selector(page, "button", r"stop|หยุดสร้าง")
        if stop is not None and stop.is_visible():
            return False
        copy = self._selector(last, "button", r"copy|คัดลอก")
        if copy is None or not copy.is_enabled():
            return False
        visible = last.inner_text(timeout=4000).strip()
        if not visible or visible == job.get("last_text"):
            job["stable"] = job.get("stable", 0) + 1
        else:
            job["stable"] = 0
            job["last_text"] = visible
        if job["stable"] < 2 or not visible:
            return False
        # One worker owns all page copy operations: there is no cross-tab race.
        try:
            origin = "https://gemini.google.com"
            job["context"].grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
            copy.click(timeout=6000)
            deadline = time.monotonic() + 7
            result = ""
            while time.monotonic() < deadline and not self._stop_requested:
                result = page.evaluate("navigator.clipboard.readText()")
                if result and result.strip():
                    break
                time.sleep(0.15)
            if not result:
                raise BrowserFailure("COPY_FAILED", "ปุ่ม Copy ไม่ส่งข้อความลง Clipboard")
            self._emit(job, "RAW:" + result, "")
        except BrowserFailure:
            raise
        except Exception as exc:
            raise BrowserFailure("COPY_FAILED", f"อ่านผล Copy ไม่สำเร็จ: {type(exc).__name__}") from exc
        return True

    def _drain_commands(self, active):
        while True:
            try:
                command, job_id = self.commands.get_nowait()
            except Empty:
                return
            if command == "stop":
                self._stop_requested = True
                return
            job = next((j for j in self.jobs if j["job_id"] == job_id), None)
            if not job:
                continue
            if command == "open" and job.get("page"):
                job["page"].bring_to_front()
            elif command == "cancel":
                active.discard(job_id)
                self._emit(job, "CANCELLED", "ผู้ใช้ยกเลิกงาน")
            elif command == "sent":
                if job.get("page"):
                    job["sent"] = True
                    active.add(job_id)
                    self._emit(job, "SUBMITTED", "ผู้ใช้ยืนยันการส่งด้วยตนเอง")
            elif command == "collect" and job.get("page"):
                active.add(job_id)
                job["stable"] = 0

    def run(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.diagnostic.emit("CHROME_LAUNCH_FAILED: ไม่มี Playwright Runtime")
            return
        self.profile_directory.mkdir(parents=True, exist_ok=True)
        try:
            with sync_playwright() as playwright:
                context = playwright.chromium.launch_persistent_context(
                    str(self.profile_directory), channel="chrome", headless=False,
                    no_viewport=True, args=["--new-window"],
                )
                try:
                    initial = context.pages
                    active = set()
                    for i, job in enumerate(self.jobs):
                        if self._stop_requested:
                            break
                        page = initial[0] if i == 0 and initial else context.new_page()
                        job["page"], job["context"] = page, context
                        self._emit(job, "OPENED")
                        try:
                            self._prepare(job)
                        except BrowserFailure as exc:
                            self._emit(job, exc.code, str(exc))
                        except Exception as exc:
                            self._emit(job, "ATTACHMENT_UPLOAD_FAILED", f"{type(exc).__name__}: {str(exc)[:160]}")
                    last_send = 0.0
                    for job in self.jobs:
                        self._drain_commands(active)
                        if self._stop_requested:
                            break
                        if job.get("page") and job.get("sent"):
                            continue
                        if not job.get("page"):
                            continue
                        if not self._attachments_ready(job["page"], [Path(p).name for p in job.get("attachments", [])]):
                            continue
                        wait = self.send_gap - (time.monotonic() - last_send)
                        if wait > 0:
                            time.sleep(wait)  # Deliberate 1-second click cadence, not an upload timer.
                        try:
                            self._send(job)
                            active.add(job["job_id"])
                        except BrowserFailure as exc:
                            self._emit(job, exc.code, str(exc))
                        except Exception as exc:
                            self._emit(job, "SEND_UNCONFIRMED", str(exc)[:180])
                        last_send = time.monotonic()
                    start = time.monotonic()
                    while not self._stop_requested:
                        self._drain_commands(active)
                        for job in self.jobs:
                            if job["job_id"] not in active or not job.get("sent"):
                                continue
                            try:
                                if self._collect(job):
                                    active.discard(job["job_id"])
                            except BrowserFailure as exc:
                                active.discard(job["job_id"])
                                self._emit(job, exc.code, str(exc))
                            except Exception as exc:
                                active.discard(job["job_id"])
                                self._emit(job, "COPY_FAILED", str(exc)[:180])
                        if time.monotonic() - start > 1800:
                            for job in self.jobs:
                                if job["job_id"] in active:
                                    self._emit(job, "RESPONSE_TIMEOUT", "ครบเวลา 30 นาที เลือกรับผลเองได้")
                            active.clear()
                        time.sleep(0.5)
                finally:
                    context.close()
        except Exception as exc:
            self.diagnostic.emit(f"CHROME_LAUNCH_FAILED/PROFILE_IN_USE: {type(exc).__name__}: {str(exc)[:250]}")
