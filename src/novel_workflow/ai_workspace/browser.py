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
        if not state.startswith("RAW:"):
            job["last_state"] = state
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
        """Prepare a tab without blocking other jobs on slow uploads."""
        page = job["page"]
        job["ready"] = False
        job["sent"] = False
        page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=25000)
        if "accounts.google.com" in page.url:
            raise BrowserFailure("GOOGLE_LOGIN_REQUIRED", "Google ขอเข้าสู่ระบบด้วยตนเอง")
        # Model selection must be verified before Gemini sees any attachments.
        self._select_model(page, job)
        attachments = [Path(p) for p in job.get("attachments", [])]
        if not attachments or any(not p.is_file() for p in attachments):
            raise BrowserFailure("ATTACHMENT_NOT_FOUND", "ไฟล์ต้นฉบับ/ไฟล์ประกอบไม่ครบ")
        for path in attachments:
            if path.stat().st_size == 0:
                raise BrowserFailure("ATTACHMENT_NOT_FOUND", f"ไฟล์ว่าง: {path.name}")
        names = [p.name for p in attachments]
        if len(set(names)) != len(names):
            raise BrowserFailure("ATTACHMENT_UPLOAD_FAILED", "มีชื่อไฟล์แนบซ้ำกัน ตรวจแยกไฟล์ไม่ได้")
        self._emit(job, "ATTACHING", f"{len(attachments)} ไฟล์")
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
        self._emit(job, "UPLOADING", "รอหลักฐานว่าไฟล์แนบพร้อมจริง")
        composer = page.locator('[contenteditable="true"]')
        if composer.count() != 1:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ไม่พบช่องพิมพ์ Prompt ที่ระบุแน่นอน")
        prompt = job.get("prompt", "").strip()
        if not prompt:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ไม่มี Prompt กรุณากรอกด้วยตนเอง")
        composer.fill(prompt, timeout=6000)
        if composer.inner_text().strip() != prompt:
            raise BrowserFailure("PROMPT_INSERT_FAILED", "ตรวจสอบข้อความ Prompt ไม่ตรง")
        job["upload_started"] = time.monotonic()
        job["upload_pending"] = True
        self._refresh_upload(job)

    @staticmethod
    def _attachments_state(page, filenames):
        """Check every expected attachment, including overflowed DOM elements.

        Unknown or virtualized/missing attachment chips are never interpreted
        as ready. An explicit upload error is different from pending progress.
        """
        return page.evaluate(r"""async (names) => {
          const input = document.querySelector('input[type=file]');
          const composer = document.querySelector('[contenteditable=true]');
          const root = input?.closest('form') || composer?.closest('form')
                    || composer?.parentElement?.parentElement;
          if (!root || !names.length || new Set(names).size !== names.length) return 'unknown';
          const seen = new Map();
          let duplicate = false;
          const examine = () => {
            const nodes = Array.from(root.querySelectorAll('[aria-label], [title], [data-file-name]'));
            for (const name of names) {
              const hits = nodes.filter(el => [el.getAttribute('data-file-name'),
                el.getAttribute('title'), el.getAttribute('aria-label')].some(
                  value => value && (value === name || value.includes(name))));
              if (hits.length > 1) duplicate = true;
              for (const el of hits) {
                const meta = [el.getAttribute('aria-label'), el.getAttribute('title'),
                  el.getAttribute('data-state'), el.getAttribute('data-status'),
                  el.textContent].join(' ').toLowerCase();
                const failed = /error|failed|rejected|ผิดพลาด|ล้มเหลว/.test(meta);
                const pending = /uploading|loading|pending|processing|กำลัง|อัปโหลดอยู่/.test(meta) ||
                  el.matches('[aria-busy=true], [role=progressbar]') ||
                  !!el.querySelector('[aria-busy=true], [role=progressbar], progress');
                const state = failed ? 'failed' : (pending ? 'pending' : 'ready');
                const prior = seen.get(name);
                if (prior && prior !== state) {
                  seen.set(name, 'pending');
                } else {
                  seen.set(name, state);
                }
              }
            }
          };
          examine();
          const scrollers = [root, ...root.querySelectorAll('*')].filter(
            el => el.scrollWidth > el.clientWidth + 5 && el.clientWidth > 0
          );
          for (const el of scrollers) {
            const start = el.scrollLeft;
            const max = el.scrollWidth - el.clientWidth;
            const step = Math.max(1, Math.floor(el.clientWidth * 0.8));
            if (Math.ceil(max / step) > 64) return "unknown";
            for (let x = 0; x <= max; x += step) {
              el.scrollLeft = x;
              el.dispatchEvent(new Event("scroll", {bubbles: true}));
              await Promise.race([new Promise(resolve => requestAnimationFrame(resolve)),
                                  new Promise(resolve => setTimeout(resolve, 100))]);
              examine();
            }
            el.scrollLeft = max;
            el.dispatchEvent(new Event("scroll", {bubbles: true}));
            await Promise.race([new Promise(resolve => requestAnimationFrame(resolve)),
                                new Promise(resolve => setTimeout(resolve, 100))]);
            examine();
            el.scrollLeft = start;
          }
          if (duplicate || names.some(name => !seen.has(name))) return 'unknown';
          if (names.some(name => seen.get(name) === 'failed')) return 'failed';
          if (names.some(name => seen.get(name) === 'pending')) return 'pending';
          return 'ready';
        }""", filenames)

    @classmethod
    def _attachments_ready(cls, page, filenames):
        return cls._attachments_state(page, filenames) == "ready"

    def _refresh_upload(self, job):
        if not job.get("upload_pending") or job.get("cancelled"):
            return
        names = [Path(path).name for path in job.get("attachments", [])]
        state = self._attachments_state(job["page"], names)
        if state == "ready":
            job["upload_pending"] = False
            job["ready"] = True
            self._emit(job, "ATTACHMENT_READY", f"ยืนยันไฟล์ {len(names)} รายการ")
            self._emit(job, "READY_TO_SEND", "ไฟล์พร้อม รอปุ่มส่ง")
        elif state == "failed":
            job["upload_pending"] = False
            self._emit(job, "ATTACHMENT_FAILED", "Gemini แจ้งข้อผิดพลาดของไฟล์แนบ")
        elif time.monotonic() - job["upload_started"] >= job.get("upload_timeout", 120):
            job["upload_pending"] = False
            self._emit(job, "ATTACHMENT_TIMEOUT", "ตรวจไฟล์ไม่ครบภายในเวลาที่กำหนด กรุณาตรวจแท็บ")
        else:
            # An opaque/virtualized chip stays pending, never silently succeeds.
            if job.get("last_state") != "UPLOADING":
                self._emit(job, "UPLOADING", "กำลังโหลดหรือยังตรวจรายการไฟล์ไม่ครบ")

    def _send(self, job):
        page = job["page"]
        expected = [Path(p).name for p in job["attachments"]]
        if not self._attachments_ready(page, expected):
            raise BrowserFailure("ATTACHMENT_NOT_READY", "ไฟล์ยังไม่พร้อม ห้ามส่งอัตโนมัติ")
        send = self._selector(page, "button", r"send|ส่ง")
        if send is None or not send.is_enabled():
            raise BrowserFailure("SEND_BUTTON_UNAVAILABLE", "ปุ่มส่งยังไม่พร้อม")
        # The click is a one-time, potentially irreversible operation.
        # Confirmation happens in later scheduler ticks so other ready
        # tabs are never blocked for nine seconds by this tab.
        job["send_attempted"] = True
        job["ready"] = False
        job["confirm_started"] = time.monotonic()
        self._emit(job, "SEND_UNCONFIRMED", "กำลังตรวจว่า Gemini รับข้อความ")
        send.click(timeout=5000)

    def _confirm_send(self, job):
        if not job.get("send_attempted") or job.get("sent"):
            return False
        page = job["page"]
        try:
            prompt = page.get_by_role("main").get_by_text(job["prompt"], exact=True)
            composer = page.locator('[contenteditable="true"]')
            composer_cleared = composer.count() == 1 and not composer.inner_text().strip()
            if composer_cleared and prompt.count() == 1 and prompt.is_visible():
                job["sent"] = True
                job["collect_started"] = time.monotonic()
                self._emit(job, "SUBMITTED", "เว็บไซต์แสดงข้อความที่ส่งแล้ว")
                return True
        except Exception:
            pass
        if time.monotonic() - job["confirm_started"] >= 15:
            job["send_attempted"] = False
            self._emit(job, "SEND_UNCONFIRMED",
                       "ยืนยันการรับ Prompt ไม่ได้ ห้ามส่งซ้ำอัตโนมัติ")
        return False

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
            sentinel = "__novel_workflow_copy_pending_" + job["job_id"] + "__"
            page.evaluate("(value) => navigator.clipboard.writeText(value)", sentinel)
            copy.click(timeout=6000)
            deadline = time.monotonic() + 7
            result = ""
            while time.monotonic() < deadline and not self._stop_requested:
                result = page.evaluate("navigator.clipboard.readText()")
                if result and result.strip() and result != sentinel:
                    break
                time.sleep(0.15)
            if not result or result == sentinel:
                raise BrowserFailure("COPY_FAILED", "ปุ่ม Copy ไม่ส่งข้อความใหม่ลง Clipboard")
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
                job["cancelled"] = True
                job["ready"] = False
                job["upload_pending"] = False
                active.discard(job_id)
                self._emit(job, "CANCELLED", "ผู้ใช้ยกเลิกงาน")
            elif command == "retry":
                if job.get("sent") or job.get("cancelled") or job.get("last_state") == "SEND_UNCONFIRMED":
                    self._emit(job, "RETRY_BLOCKED", "มีโอกาสส่งแล้ว · ห้ามส่งซ้ำโดยไม่ตรวจแท็บ")
                    continue
                try:
                    self._prepare(job)
                    if job.get("ready"):
                        self._send(job)
                    if job.get("send_attempted"):
                        active.add(job_id)
                except BrowserFailure as exc:
                    self._emit(job, exc.code, str(exc))
                except Exception as exc:
                    self._emit(job, "ATTACHMENT_UPLOAD_FAILED", f"{type(exc).__name__}: {str(exc)[:180]}")
            elif command == "sent":
                if job.get("page"):
                    job["sent"] = True
                    job["collect_started"] = time.monotonic()
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
                # Keep Chrome open while assisted recovery is possible. When
                # stopped, Playwright must release the persistent profile lock.
                try:
                    initial = context.pages
                    active = set()
                    last_send = 0.0
                    for i, job in enumerate(self.jobs):
                        self._drain_commands(active)
                        if self._stop_requested:
                            break
                        page = initial[0] if i == 0 and initial else context.new_page()
                        job["page"], job["context"] = page, context
                        self._emit(job, "OPENED")
                        try:
                            self._prepare(job)
                        except BrowserFailure as exc:
                            job["upload_pending"] = False
                            self._emit(job, exc.code, str(exc))
                        except Exception as exc:
                            job["upload_pending"] = False
                            self._emit(job, "ATTACHMENT_UPLOAD_FAILED",
                                       f"{type(exc).__name__}: {str(exc)[:160]}")
                        # Dispatch already-ready tabs while preparing later ones.
                        # A slow upload on this or a previous tab is not a barrier.
                        for candidate in self.jobs[:i + 1]:
                            if (not candidate.get("ready") or candidate.get("sent")
                                    or candidate.get("send_attempted")
                                    or candidate.get("cancelled")):
                                continue
                            if time.monotonic() - last_send < self.send_gap:
                                break
                            try:
                                self._send(candidate)
                                active.add(candidate["job_id"])
                            except BrowserFailure as exc:
                                candidate["ready"] = False
                                self._emit(candidate, exc.code, str(exc))
                            except Exception as exc:
                                candidate["ready"] = False
                                self._emit(candidate, "SEND_UNCONFIRMED", str(exc)[:180])
                            last_send = time.monotonic()
                            break
                    while not self._stop_requested:
                        self._drain_commands(active)
                        pending = [j for j in self.jobs if j.get("upload_pending")
                                   and not j.get("cancelled")]
                        for job in pending:
                            try:
                                self._refresh_upload(job)
                            except Exception as exc:
                                job["upload_pending"] = False
                                self._emit(job, "ATTACHMENT_FAILED",
                                           f"ตรวจไฟล์ไม่สำเร็จ: {type(exc).__name__}")
                        for job in self.jobs:
                            if (job.get("cancelled") or not job.get("ready")
                                    or job.get("sent") or job.get("send_attempted")
                                    or not job.get("page")):
                                continue
                            # Send in submission order among *ready* jobs;
                            # never block ready work on a still-uploading tab.
                            remaining = self.send_gap - (time.monotonic() - last_send)
                            if remaining > 0:
                                continue
                            try:
                                self._send(job)
                                active.add(job["job_id"])
                            except BrowserFailure as exc:
                                job["ready"] = False
                                self._emit(job, exc.code, str(exc))
                            except Exception as exc:
                                job["ready"] = False
                                self._emit(job, "SEND_UNCONFIRMED", str(exc)[:180])
                            last_send = time.monotonic()
                            break
                        for job in self.jobs:
                            if job["job_id"] in active and job.get("send_attempted") and not job.get("sent"):
                                self._confirm_send(job)
                                if not job.get("send_attempted") and not job.get("sent"):
                                    active.discard(job["job_id"])
                            if job["job_id"] not in active or not job.get("sent"):
                                continue
                            if (time.monotonic() - job.get("collect_started", time.monotonic())
                                    > job.get("response_timeout", 1800)):
                                active.discard(job["job_id"])
                                self._emit(job, "RESPONSE_TIMEOUT",
                                           "เกินเวลารอคำตอบ กรุณารับผลเองจากแท็บเดิม")
                                continue
                            try:
                                if self._collect(job):
                                    job["collected"] = True
                                    active.discard(job["job_id"])
                            except BrowserFailure as exc:
                                active.discard(job["job_id"])
                                self._emit(job, exc.code, str(exc))
                            except Exception as exc:
                                active.discard(job["job_id"])
                                self._emit(job, "COPY_FAILED", str(exc)[:180])
                        # Do not spin after a batch has completed. Keep the
                        # profile/session available for explicit manual recovery.
                        if (not getattr(self, "_batch_done", False) and self.jobs
                                and all(j.get("collected") or j.get("cancelled")
                                        for j in self.jobs)):
                            self._batch_done = True
                            self.diagnostic.emit("รับผล Gemini ครบทุกงานแล้ว · ตรวจผลและ Export ได้")
                        remaining_to_send = any(j.get("ready") and not j.get("sent")
                                                for j in self.jobs)
                        remaining_uploads = any(j.get("upload_pending") for j in self.jobs)
                        if not active and not remaining_to_send and not remaining_uploads:
                            try:
                                command = self.commands.get(timeout=5)
                                self.commands.put(command)
                            except Empty:
                                pass
                        else:
                            time.sleep(0.5)
                finally:
                    context.close()
        except Exception as exc:
            self.diagnostic.emit(
                f"CHROME_LAUNCH_FAILED/PROFILE_IN_USE: {type(exc).__name__}: {str(exc)[:250]}")
