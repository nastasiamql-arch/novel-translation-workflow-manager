"""Windows integration smoke: spawn the installed, non-automated Google Chrome.

This verifies executable resolution and a real OS spawn only. It intentionally
does not claim a Gemini sign-in, DOM inspection, or successful tab placement.
"""
import sys
from novel_workflow.ai_workspace.standard_chrome import (
    StandardChromeLauncher, find_chrome, GEMINI_URL,
)

if __name__ == "__main__":
    assert sys.platform == "win32", "Run on a Windows GitHub Actions runner"
    exe = find_chrome()
    assert exe.is_file() and exe.name.casefold() == "chrome.exe"
    launched = StandardChromeLauncher().open_urls([GEMINI_URL])
    assert launched == 1
    print(f"Standard Chrome OS launch requested via: {exe.name}")
    print("Note: Google session/login and window placement were NOT verified.")
