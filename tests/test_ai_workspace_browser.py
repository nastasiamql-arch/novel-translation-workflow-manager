"""Real DOM browser fixture tests; intentionally NOT live Gemini acceptance tests."""
import os
import pytest

from novel_workflow.ai_workspace.browser import GeminiBrowserWorker


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        try:
            client = runner.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
            if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
                pytest.fail(f"Required Chrome browser fixture unavailable: {exc}")
            pytest.skip(f"Chrome missing from fixture runner: {exc}")
        try:
            yield client
        finally:
            client.close()


def html(*, busy=False, extra=False, duplicate=False):
    one = '<span aria-label="475.txt" data-file-name="475.txt"></span>'
    two = ('<span aria-label="476.txt" data-file-name="476.txt">'
           + ('<span role="progressbar"></span>' if busy else '') + '</span>')
    duplicated = two if duplicate else ""
    return (f'<form><input type="file" multiple><div style="width:20px;overflow:hidden">'
            f'{one}{two}{duplicated}</div>'
            f'<button type="button">Send</button><div contenteditable="true"></div></form>')


def test_attachment_dom_including_overflow_and_pending(browser):
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_content(html())
        assert GeminiBrowserWorker._attachments_ready(page, ["475.txt", "476.txt"])
        page.set_content(html(busy=True))
        assert not GeminiBrowserWorker._attachments_ready(page, ["475.txt", "476.txt"])
        page.set_content(html(duplicate=True))
        assert not GeminiBrowserWorker._attachments_ready(page, ["475.txt", "476.txt"])
        assert not GeminiBrowserWorker._attachments_ready(page, ["475.txt", "missing.txt"])
    finally:
        context.close()


def test_ten_tabs_one_browser_context(browser):
    context = browser.new_context()
    try:
        pages = [context.new_page() for _ in range(10)]
        assert len(pages) == len(context.pages) == 10
        assert len({page.context for page in pages}) == 1
    finally:
        context.close()

def test_attachment_state_distinguishes_pending_failed_unknown(browser):
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_content(html(busy=True))
        assert GeminiBrowserWorker._attachments_state(page, ["475.txt", "476.txt"]) == "pending"
        page.set_content(html())
        assert GeminiBrowserWorker._attachments_state(page, ["475.txt", "476.txt"]) == "ready"
        assert GeminiBrowserWorker._attachments_state(page, ["475.txt", "missing.txt"]) == "unknown"
        page.set_content(html(duplicate=True))
        assert GeminiBrowserWorker._attachments_state(page, ["475.txt", "476.txt"]) == "unknown"
        page.set_content(html().replace('aria-label="476.txt"', 'aria-label="476.txt error"'))
        assert GeminiBrowserWorker._attachments_state(page, ["475.txt", "476.txt"]) == "failed"
    finally:
        context.close()


def test_upload_polling_does_not_fail_while_busy(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import time
    worker = GeminiBrowserWorker([], tmp_path)
    events = []
    worker.event.connect(lambda jid, state, reason, url: events.append(state))
    job = dict(job_id="one", page=SimpleNamespace(url="https://gemini.google.com/app"),
               attachments=["475.txt"], upload_pending=True,
               upload_started=time.monotonic(), upload_timeout=10)
    monkeypatch.setattr(worker, "_attachments_state", lambda page, filenames: "pending")
    worker._refresh_upload(job)
    assert job["upload_pending"]
    assert not job.get("ready")
    assert events[-1] == "UPLOADING"
    monkeypatch.setattr(worker, "_attachments_state", lambda page, filenames: "ready")
    worker._refresh_upload(job)
    assert job["ready"] and not job["upload_pending"]
    assert events[-1] == "READY_TO_SEND"


def test_upload_timeout_is_not_success(monkeypatch, tmp_path):
    from types import SimpleNamespace
    import time
    worker = GeminiBrowserWorker([], tmp_path)
    events = []
    worker.event.connect(lambda jid, state, reason, url: events.append(state))
    monkeypatch.setattr(worker, "_attachments_state", lambda page, filenames: "unknown")
    job = dict(job_id="one", page=SimpleNamespace(url=""),
               attachments=["475.txt"], upload_pending=True,
               upload_started=time.monotonic() - 60, upload_timeout=1)
    worker._refresh_upload(job)
    assert not job["upload_pending"] and not job.get("ready")
    assert events[-1] == "ATTACHMENT_TIMEOUT"

def test_send_confirmation_is_deferred_and_idempotent(browser, tmp_path):
    context = browser.new_context()
    try:
        page = context.new_page()
        page.set_content(html() + '<main></main>')
        worker = GeminiBrowserWorker([], tmp_path)
        job = {"job_id": "send-once", "page": page, "context": context,
               "prompt": "TRANSLATE CHAPTER 475", "attachments": ["475.txt", "476.txt"]}
        events = []
        worker.event.connect(lambda jid, state, reason, url: events.append(state))
        worker._send(job)
        assert job["send_attempted"] and not job.get("sent")
        assert events[-1] == "SEND_UNCONFIRMED"
        assert not worker._confirm_send(job)
        page.locator("main").evaluate("(el) => el.textContent = 'TRANSLATE CHAPTER 475'")
        assert worker._confirm_send(job)
        assert job["sent"] and events[-1] == "SUBMITTED"
        assert not worker._confirm_send(job)
        assert events.count("SUBMITTED") == 1
    finally:
        context.close()
