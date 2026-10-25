"""Regressions for Windows Qt shutdown result interpretation."""
import runpy
from pathlib import Path


def test_warning_only_pytest_result_remains_a_pass():
    runner = runpy.run_path(str(Path(__file__).with_name("run_suite_groups.py")))
    clean = runner["pytest_passed_cleanly"]
    assert clean("164 passed, 1 warning in 61.52s\nPytest completed; exit status: 0")
    assert clean("90 passed in 29.06s\nPytest completed; exit status: 0")
    assert clean("================ 84 passed in 55.91s ================\nPytest completed; exit status: 0")
    assert clean("test_failed_save PASSED\n90 passed in 29.06s\nPytest completed; exit status: 0")
    assert not clean("test_something FAILED\n1 failed, 89 passed in 10s")
    assert not clean("= FAILURES =\n90 passed in 29s\nPytest completed; exit status: 0")
