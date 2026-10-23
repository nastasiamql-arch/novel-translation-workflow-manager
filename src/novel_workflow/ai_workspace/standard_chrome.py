"""Open the user's *ordinary* Google Chrome; never automate Google authentication.

No CDP, remote debugging, injected flags, profile copying, or browser shutdown.
A successful process spawn proves only a launch request, not tab/login readiness.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

GEMINI_URL = "https://gemini.google.com/app"


class ChromeLaunchError(RuntimeError):
    """Chrome executable is missing or the OS refused the launch."""


def find_chrome(configured: str = "") -> Path:
    """Use an explicit executable or an installed Windows Chrome, never a bundled driver."""
    if configured.strip():
        path = Path(configured.strip().strip('"')).expanduser()
        if not path.is_file() or path.name.casefold() != "chrome.exe":
            raise ChromeLaunchError("โปรดเลือกไฟล์ chrome.exe ที่มีอยู่จริง")
        return path.resolve()

    candidates = []
    if sys.platform == "win32":
        try:
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                        candidates.append(Path(winreg.QueryValueEx(key, "")[0]))
                except OSError:
                    pass
        except ImportError:
            pass
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if os.environ.get(env):
                candidates.append(Path(os.environ[env]) / "Google" / "Chrome" / "Application" / "chrome.exe")
    found = shutil.which("chrome.exe") if sys.platform == "win32" else None
    if found:
        candidates.append(Path(found))
    for path in candidates:
        if path.is_file() and path.name.casefold() == "chrome.exe":
            return path.resolve()
    raise ChromeLaunchError("ไม่พบ Google Chrome ปกติ กรุณาระบุ chrome.exe ด้วยตนเอง")


def validate_gemini_url(url: str) -> str:
    """Prevent switches, arbitrary schemes, and redirects through untrusted URLs."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "gemini.google.com"
            or parts.port not in (None, 443) or not parts.path.startswith("/app")
            or parts.username or parts.password or any(c.isspace() for c in url)):
        raise ChromeLaunchError("เปิดได้เฉพาะ Gemini URL ที่ปลอดภัย")
    return url


class StandardChromeLauncher:
    def __init__(self, executable: str = ""):
        self.executable = executable

    def open_urls(self, urls, *, new_window: bool = True) -> int:
        targets = list(urls)
        if not 1 <= len(targets) <= 10:
            raise ChromeLaunchError("เปิดได้ครั้งละ 1–10 แท็บ")
        targets = [validate_gemini_url(url) for url in targets]
        chrome = find_chrome(self.executable)
        # Multiple URL arguments in a single invocation request a single
        # window. An already-running Chrome may redirect to an existing window;
        # the UI deliberately does not assert that tab placement was verified.
        args = [str(chrome)]
        if new_window:
            args.append("--new-window")
        args.extend(targets)
        try:
            subprocess.Popen(args, shell=False, close_fds=True)
        except OSError as exc:
            raise ChromeLaunchError(f"Windows เปิด Chrome ไม่สำเร็จ: {exc}") from exc
        return len(targets)
