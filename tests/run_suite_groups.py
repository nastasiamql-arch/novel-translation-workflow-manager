"""Run every pytest module in bounded Windows Qt subprocesses.

Only a successful pytest result marker plus a passing assertion summary may
recover known native Qt crash-at-exit errors. Collection/assertion failures,
missing output, and every other nonzero code remain failures.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path


QT_SHUTDOWN_CODES = {3221225477, 3221226505}  # 0xC0000005, 0xC0000409
SUCCESS_MARKER = "Pytest completed; exit status: 0"


def pytest_passed_cleanly(output: str) -> bool:
    summary = re.search(
        r"(?m)^=*\s*\d+ passed(?:, \d+ (?:skipped|xfailed|warnings?))* in ", output
    )
    failures = re.search(
        r"(?im)^(?:FAILED|ERROR)\b|^=+ (?:FAILURES|ERRORS) =+", output
    )
    return SUCCESS_MARKER in output and summary is not None and failures is None


def main() -> int:
    tests = sorted(Path(__file__).parent.glob("test_*.py"))
    if not tests:
        print("No test modules found", file=sys.stderr, flush=True)
        return 2
    # Keep the long-running Qt history page tests in their own interpreter.
    # Their QThread-backed filesystem scans must not share Qt teardown state
    # with unrelated test modules on Windows.
    chunks = []
    pending = []
    for test in tests:
        if test.name == "test_polish_history_ui.py":
            if pending:
                chunks.append(pending)
                pending = []
            chunks.append([test])
            continue
        pending.append(test)
        if len(pending) == 8:
            chunks.append(pending)
            pending = []
    if pending:
        chunks.append(pending)
    print(f"Testing {len(tests)} modules in {len(chunks)} isolated processes", flush=True)
    for n, chunk in enumerate(chunks, 1):
        print(f"Group {n}/{len(chunks)}: {', '.join(p.name for p in chunk)}", flush=True)
        cmd = [
            sys.executable, str(Path(__file__).with_name("run_pytest_group.py")),
            "-vv", "--durations=5", "-o", "faulthandler_timeout=60",
            *(str(path) for path in chunk),
        ]
        # A file-backed log survives Windows' asynchronous native Qt crash
        # even if the interpreter cannot close stdout pipes normally.
        with tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as log:
            completed = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=False)
            log.seek(0)
            output = log.read()
        print(output, end="" if output.endswith("\n") else "\n", flush=True)
        result = completed.returncode
        if result == 0:
            continue
        unsigned = result & 0xFFFFFFFF
        clean_pytest = pytest_passed_cleanly(output)
        if unsigned in QT_SHUTDOWN_CODES and clean_pytest:
            print(
                f"WARNING: Group {n} passed all pytest assertions; "
                f"Qt crashed during native Windows process shutdown (0x{unsigned:08X}).",
                flush=True,
            )
            continue
        print(f"Test group {n} failed (exit code {result})", file=sys.stderr, flush=True)
        return result if 0 < result < 256 else 1
    print("All isolated pytest groups passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
