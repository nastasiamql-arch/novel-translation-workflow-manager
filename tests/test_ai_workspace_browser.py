"""Real DOM browser fixture tests; intentionally NOT live Gemini acceptance tests."""
import pytest

from novel_workflow.ai_workspace.browser import GeminiBrowserWorker


@pytest.fixture(scope="module")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    with playwright.sync_playwright() as runner:
        try:
            client = runner.chromium.launch(channel="chrome", headless=True)
        except playwright.Error as exc:
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
