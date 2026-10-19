"""Regression checks for the Valhalla name and editor performance path."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_brand_name_and_legacy_install_identity():
    main = (ROOT / "src/novel_workflow/main.py").read_text(encoding="utf-8")
    installer = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert 'setApplicationName("Valhalla")' in main
    assert '#define MyAppName "Valhalla"' in installer
    assert 'B93AE24C-43D9-4D38-A880-93A607EA8D41' in installer
    assert '#define MyAppExeName "NovelWorkflow.exe"' in installer
    assert 'OutputBaseFilename=NovelWorkflow-Setup-' in installer
    assert 'Name: "{autoprograms}\\Valhalla"' in installer


def test_cursor_status_has_no_disk_or_export_work():
    source = (ROOT / "src/novel_workflow/workspace_window.py").read_text(encoding="utf-8")
    block = source.split("    def _workspace_editor_status_changed(", 1)[1].split("    def _update_editor_status(", 1)[0]
    assert "self.editor_status.setFullText(text)" in block
    assert "refresh_export_status" not in block
    assert "latest_context_chapter" not in block


def test_winged_brand_assets_are_packaged():
    root = ROOT / "src/novel_workflow/resources"
    assert (root / "valhalla-logo.png").read_bytes().startswith(b"\x89PNG")
    assert (root / "valhalla-icon.png").read_bytes().startswith(b"\x89PNG")
    spec = (ROOT / "NovelWorkflow.spec").read_text(encoding="utf-8")
    assert "valhalla-icon.png" in spec
    assert "valhalla.ico" in spec
