import json

import pytest

from novel_workflow.downloader.manifest import ChapterManifest, ManifestError


def test_manifest_utf8_roundtrip_and_missing_file(tmp_path):
    path = tmp_path / "source_meta" / "manifest.json"
    manifest = ChapterManifest(path)
    manifest.configure("tomatomtl", "1", "https://tomatomtl.com/book/1")
    manifest.record("remote-1", index=1, title="第一章", filename="0001 第一章.txt", content_hash="abc")
    loaded = ChapterManifest(path)
    assert "第一章" in path.read_text(encoding="utf-8")
    assert loaded.data["chapters"]["remote-1"]["index"] == 1
    assert ChapterManifest(tmp_path / "absent.json").data["chapters"] == {}


def test_corrupt_manifest_is_not_overwritten(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ManifestError): ChapterManifest(path)
    assert path.read_text(encoding="utf-8") == "{broken"


def test_save_uses_replace(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    manifest = ChapterManifest(path)
    calls = []
    import novel_workflow.downloader.manifest as module
    real_replace = module.os.replace
    monkeypatch.setattr(module.os, "replace", lambda a, b: (calls.append((a, b)), real_replace(a, b))[1])
    manifest.save()
    assert calls and path.exists()
