import hashlib
import io
from pathlib import Path

import pytest

from novel_workflow import __version__
from novel_workflow import updater


def release_payload(version="1.8.0", content=b"installer bytes"):
    digest = hashlib.sha256(content).hexdigest()
    return {
        "tag_name": f"v{version}",
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/nastasiamql-arch/novel-translation-workflow-manager/releases/tag/v{version}",
        "body": "Bug fixes and improvements",
        "assets": [{
            "name": f"NovelWorkflow-Setup-{version}.exe",
            "size": len(content),
            "digest": f"sha256:{digest}",
            "browser_download_url": (
                "https://github.com/nastasiamql-arch/novel-translation-workflow-manager/"
                f"releases/download/v{version}/NovelWorkflow-Setup-{version}.exe"
            ),
        }],
    }


def test_latest_release_is_available_only_when_its_version_is_newer():
    available = updater.parse_latest_release(release_payload(), "1.7.5")
    current = updater.parse_latest_release(release_payload("1.7.5"), "1.7.5")

    assert available.version == "1.8.0"
    assert available.sha256 == hashlib.sha256(b"installer bytes").hexdigest()
    assert current is None


def test_release_without_valid_sha256_is_rejected():
    payload = release_payload()
    payload["assets"][0]["digest"] = "sha256:bad"

    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.parse_latest_release(payload, "1.7.5")


def test_download_verifies_hash_before_publishing_installer(tmp_path, monkeypatch):
    content = b"verified installer"
    release = updater.parse_latest_release(release_payload(content=content), "1.7.5")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(updater, "urlopen", lambda *_args, **_kwargs: Response(content))
    destination = tmp_path / "NovelWorkflow-Setup-1.8.0.exe"
    progress = []

    result = updater.download_update(release, destination, progress.append)

    assert result == destination
    assert destination.read_bytes() == content
    assert progress[-1] == 100


def test_bad_download_is_removed_instead_of_left_as_installer(tmp_path, monkeypatch):
    release = updater.parse_latest_release(release_payload(), "1.7.5")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(updater, "urlopen", lambda *_args, **_kwargs: Response(b"tampered bytes!"))
    destination = tmp_path / "NovelWorkflow-Setup-1.8.0.exe"

    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.download_update(release, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))


def test_runtime_version_comes_from_installed_project_metadata():
    from importlib.metadata import version

    assert __version__ == version("novelworkflow")
