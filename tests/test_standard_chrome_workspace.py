"""Standard Chrome launcher and manual-response workflow regression tests."""
from pathlib import Path
from types import SimpleNamespace
import subprocess
import pytest

from novel_workflow.ai_workspace.standard_chrome import (
    ChromeLaunchError, StandardChromeLauncher, GEMINI_URL, validate_gemini_url,
)
from novel_workflow.ai_workspace.core import build_jobs, ordered_results
from novel_workflow.ai_workspace.manual_results import accept_clipboard_response


def chapter(n):
    return SimpleNamespace(number=n, path=Path(f"{n}.txt"))


def answer(n):
    return f"บทที่ {n}\nเนื้อหาแปล {n}\n[จบตอน]\nคำศัพท์ใหม่\n[-]\n"


def test_launcher_invokes_real_chrome_path_without_playwright(monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"fake")
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: calls.append((args, kwargs)))
    launcher = StandardChromeLauncher(str(exe))
    assert launcher.open_urls([GEMINI_URL] * 10) == 10
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[0] == str(exe.resolve())
    assert args[1] == "--new-window"
    assert args[2:] == [GEMINI_URL] * 10
    assert kwargs["shell"] is False
    assert launcher.open_urls([GEMINI_URL], new_window=False) == 1
    assert "--new-window" not in calls[-1][0]


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "http://gemini.google.com/app",
    "https://gemini.google.com.evil.tld/app",
    "https://user:password@gemini.google.com/app",
    "https://gemini.google.com:444/app",
    "https://gemini.google.com/elsewhere",
])
def test_launcher_rejects_untrusted_urls(url, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.touch()
    with pytest.raises(ChromeLaunchError):
        StandardChromeLauncher(str(exe)).open_urls([url])


def test_launcher_rejects_more_than_ten(tmp_path):
    with pytest.raises(ChromeLaunchError):
        StandardChromeLauncher().open_urls([GEMINI_URL] * 11)


def test_wrong_job_duplicate_and_ordering():
    jobs = build_jobs("a"*32, "แปล", [chapter(n) for n in range(701, 731)], 3)
    with pytest.raises(ValueError, match="WRONG_JOB"):
        accept_clipboard_response(jobs[2], "".join(answer(n) for n in (719, 720, 721)))
    assert not jobs[2].raw_response
    for job in reversed(jobs):
        response = "".join(answer(n) for n in job.chapter_numbers)
        assert accept_clipboard_response(job, response)
        assert not accept_clipboard_response(job, response)
    assert ordered_results(jobs).count("[จบตอน]") == 30
    assert ordered_results(jobs).index("บทที่ 701") < ordered_results(jobs).index("บทที่ 730")


def test_manual_response_never_overwrites_original():
    job = build_jobs("a"*32, "แปล", [chapter(475)], 1)[0]
    assert accept_clipboard_response(job, answer(475))
    with pytest.raises(ValueError, match="CONFLICT"):
        accept_clipboard_response(job, answer(475).replace("เนื้อหาแปล", "แก้เนื้อหา"))
    assert job.raw_response == answer(475)


def test_manual_invalid_response_is_review_only():
    job = build_jobs("a"*32, "แปล", [chapter(475)], 1)[0]
    assert accept_clipboard_response(job, "invalid")
    assert job.status == "REVIEW_REQUIRED"
    assert job.raw_response == "invalid"
