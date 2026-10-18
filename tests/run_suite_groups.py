"""Run the complete pytest module set in bounded Windows Qt processes.

PySide6 keeps native QApplication widgets alive across test modules. A
single long Windows run can report every test passed yet return exit code 1
from native Qt shutdown. Avoid shared Qt lifetime across all test modules. Isolate groups
without suppressing pytest failures or exit codes.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    tests = sorted(Path(__file__).parent.glob("test_*.py"))
    if not tests:
        print("No test modules found", file=sys.stderr, flush=True)
        return 2
    chunks = [tests[i:i + 8] for i in range(0, len(tests), 8)]
    print(f"Testing {len(tests)} modules in {len(chunks)} isolated processes", flush=True)
    for n, chunk in enumerate(chunks, 1):
        print(f"Group {n}/{len(chunks)}: {', '.join(p.name for p in chunk)}", flush=True)
        cmd = [
            sys.executable, str(Path(__file__).with_name("run_pytest_group.py")), "-q", "--durations=5",
            "-o", "faulthandler_timeout=60",
            *(str(path) for path in chunk),
        ]
        completed = subprocess.run(cmd, check=False)
        if completed.returncode:
            print(f"Test group {n} failed (exit code {completed.returncode})", file=sys.stderr, flush=True)
            return completed.returncode
    print("All isolated pytest groups passed", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
