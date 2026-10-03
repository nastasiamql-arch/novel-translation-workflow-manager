import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

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
            "id": 123456,
            "url": (
                "https://api.github.com/repos/nastasiamql-arch/novel-translation-workflow-manager/"
                "releases/assets/123456"
            ),
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
    assert available.asset_api_url.endswith("/releases/assets/123456")
    assert current is None


def test_release_without_valid_sha256_is_rejected():
    payload = release_payload()
    payload["assets"][0]["digest"] = "sha256:bad"

    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.parse_latest_release(payload, "1.7.5")


def test_download_verifies_hash_before_publishing_installer(tmp_path, monkeypatch):
    content = b"verified installer"
    release = updater.parse_latest_release(release_payload(content=content), "1.7.5")
    token = "test-private-download-token"
    monkeypatch.setattr(updater.shutil, "which", lambda name: "gh.exe" if name == "gh" else None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{token}\n"),
    )

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    requests = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request)
        return Response(content)

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    destination = tmp_path / "NovelWorkflow-Setup-1.8.0.exe"
    progress = []

    result = updater.download_update(release, destination, progress.append)

    assert result == destination
    assert destination.read_bytes() == content
    assert progress[-1] == 100
    assert requests[0].get_header("Authorization") == f"Bearer {token}"
    assert requests[0].get_header("Accept") == "application/octet-stream"
    assert requests[0].full_url == release.asset_api_url


def test_release_without_valid_asset_api_url_is_rejected():
    payload = release_payload()
    payload["assets"][0]["url"] = "https://attacker.example/installer.exe"

    with pytest.raises(updater.UpdateError, match="API"):
        updater.parse_latest_release(payload, "1.7.5")


def test_invalid_release_version_and_wrong_installer_asset_are_rejected():
    with pytest.raises(updater.UpdateError, match="เลขเวอร์ชัน"):
        updater.parse_latest_release(release_payload("not-a-version"), "1.7.5")
    payload = release_payload()
    payload["assets"][0]["name"] = "Other-Setup-1.8.0.exe"
    with pytest.raises(updater.UpdateError, match="ไฟล์ติดตั้ง"):
        updater.parse_latest_release(payload, "1.7.5")


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


def test_size_mismatch_and_interrupted_download_never_publish_installer(tmp_path, monkeypatch):
    release = updater.parse_latest_release(release_payload(), "1.7.5")

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    destination = tmp_path / "setup.exe"
    monkeypatch.setattr(updater, "urlopen", lambda *_args, **_kwargs: Response(b"x" * 30))
    with pytest.raises(updater.UpdateError, match="เกิน"):
        updater.download_update(release, destination)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))

    monkeypatch.setattr(updater, "urlopen", lambda *_args, **_kwargs: Response(b"installer bytes"))
    with pytest.raises(updater.UpdateError, match="ยกเลิก"):
        updater.download_update(release, destination, cancelled=lambda: True)
    assert not destination.exists()
    assert not list(tmp_path.glob("*.part"))


def test_runtime_version_comes_from_installed_project_metadata():
    from importlib.metadata import version

    assert __version__ == version("novelworkflow")


def test_check_uses_github_cli_credential_without_persisting_it(monkeypatch):
    token = "test-private-token"
    monkeypatch.setattr(updater.shutil, "which", lambda name: "gh.exe" if name == "gh" else None)
    monkeypatch.setattr(
        updater.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{token}\n"),
    )
    response = io.BytesIO(json.dumps(release_payload("1.8.1")).encode())
    requests = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request)
        return response

    monkeypatch.setattr(updater, "urlopen", fake_urlopen)
    updater.check_for_update("1.8.0")

    assert requests[0].get_header("Authorization") == f"Bearer {token}"
    assert not any(value == token for value in updater.__dict__.values())


def test_unauthenticated_private_repository_404_explains_how_to_sign_in(monkeypatch):
    from urllib.error import HTTPError

    monkeypatch.setattr(updater.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        updater,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            HTTPError(updater.LATEST_RELEASE_URL, 404, "Not Found", {}, None)
        ),
    )

    with pytest.raises(updater.UpdateError, match="Private|private|gh auth login"):
        updater.check_for_update("1.8.0")
