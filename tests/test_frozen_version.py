import importlib.metadata
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_frozen_version_ignores_stale_distribution_metadata(tmp_path, monkeypatch):
    package = tmp_path / 'novel_workflow'
    resources = package / 'resources'
    resources.mkdir(parents=True)
    (resources / 'app-version.txt').write_text('3.4.2', encoding='utf-8')
    entry = package / '__init__.py'
    entry.write_text((ROOT / 'src/novel_workflow/__init__.py').read_text(encoding='utf-8'), encoding='utf-8')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(importlib.metadata, 'version', lambda _name: '1.12.0')
    assert runpy.run_path(str(entry))['__version__'] == '3.4.2'


def test_installer_removes_only_application_distribution_metadata():
    text = (ROOT / 'installer.iss').read_text(encoding='utf-8')
    assert 'Name: "{app}\\_internal\\novelworkflow-*.dist-info"' in text
    assert 'Name: "{app}\\novelworkflow-*.dist-info"' in text
    assert 'Name: "{app}\\*"' not in text
