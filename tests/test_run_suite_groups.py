"""Regressions for Windows Qt shutdown result interpretation."""
import re
from pathlib import Path


def test_warning_only_pytest_result_remains_a_pass():
    text = Path(__file__).with_name("run_suite_groups.py").read_text(encoding="utf-8")
    pattern = re.search(r'and re.search\(r"([^"]+)", output\)', text).group(1)
    assert re.search(pattern, "164 passed, 1 warning in 61.52s")
    assert re.search(pattern, "90 passed in 29.06s")
    assert not re.search(pattern, "163 passed, 1 failed, 1 warning in 61.52s")
