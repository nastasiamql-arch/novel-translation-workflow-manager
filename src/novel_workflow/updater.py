"""GitHub Releases update discovery and verified installer downloads."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


REPOSITORY = "nastasiamql-arch/novel-translation-workflow-manager"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASE_DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateError(Exception):
    """An update could not be checked or verified."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    release_url: str
    download_url: str
    sha256: str
    size: int
    notes: str


def _version_parts(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(str(value).strip())
    if not match:
        raise UpdateError(f"รูปแบบเลขเวอร์ชันไม่ถูกต้อง: {value}")
    return tuple(int(part) for part in match.groups())


def parse_latest_release(payload: dict, current_version: str) -> UpdateInfo | None:
    """Return a verified release descriptor only when it is newer."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        raise UpdateError("ข้อมูล Release ไม่ถูกต้องหรือไม่ใช่รุ่นเสถียร")

    tag = payload.get("tag_name", "")
    version = tag[1:] if isinstance(tag, str) and tag.startswith("v") else tag
    if _version_parts(version) <= _version_parts(current_version):
        return None

    release_url = payload.get("html_url", "")
    expected_release_url = f"https://github.com/{REPOSITORY}/releases/tag/{tag}"
    if release_url != expected_release_url:
        raise UpdateError("ลิงก์ Release ไม่ตรงกับ repository ทางการ")

    asset_name = f"NovelWorkflow-Setup-{version}.exe"
    assets = payload.get("assets")
    asset = next((item for item in assets or [] if item.get("name") == asset_name), None)
    if not asset:
        raise UpdateError("Release นี้ไม่มีไฟล์ติดตั้งที่ถูกต้อง")

    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:"):
        digest = digest.removeprefix("sha256:")
    if not _SHA256.fullmatch(digest):
        raise UpdateError("Release ไม่มีค่า SHA-256 สำหรับตรวจไฟล์")

    download_url = asset.get("browser_download_url", "")
    expected_download_url = RELEASE_DOWNLOAD_PREFIX + f"{tag}/{asset_name}"
    if download_url != expected_download_url:
        raise UpdateError("ลิงก์ดาวน์โหลดไม่ตรงกับ installer ของ repository ทางการ")

    size = asset.get("size")
    if not isinstance(size, int) or size <= 0:
        raise UpdateError("ขนาดไฟล์ติดตั้งใน Release ไม่ถูกต้อง")

    return UpdateInfo(
        version=version,
        release_url=release_url,
        download_url=download_url,
        sha256=digest.lower(),
        size=size,
        notes=str(payload.get("body") or "").strip(),
    )


def check_for_update(current_version: str, timeout: int = 8) -> UpdateInfo | None:
    request = Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"NovelWorkflow/{current_version}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"ตรวจสอบอัปเดตไม่ได้: {exc}") from exc
    return parse_latest_release(payload, current_version)


def download_update(
    update: UpdateInfo,
    destination: Path,
    progress=None,
    cancelled=None,
    timeout: int = 30,
) -> Path:
    """Download an installer, verify size and SHA-256, then atomically publish it."""
    destination = Path(destination)
    part_path = destination.with_name(destination.name + ".part")
    request = Request(
        update.download_url,
        headers={"User-Agent": f"NovelWorkflow/{update.version}"},
    )
    digest = hashlib.sha256()
    received = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urlopen(request, timeout=timeout) as response, part_path.open("wb") as output:
            final_url = response.geturl() if hasattr(response, "geturl") else update.download_url
            if not str(final_url).startswith("https://"):
                raise UpdateError("การเชื่อมต่อดาวน์โหลดไม่ปลอดภัย")
            while True:
                if cancelled and cancelled():
                    raise UpdateError("ยกเลิกการดาวน์โหลดแล้ว")
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > update.size:
                    raise UpdateError("ไฟล์ดาวน์โหลดมีขนาดเกินกว่าที่ Release แจ้ง")
                digest.update(chunk)
                output.write(chunk)
                if progress:
                    progress(min(100, received * 100 // update.size))
            output.flush()
            os.fsync(output.fileno())
        if received != update.size:
            raise UpdateError("ดาวน์โหลดไม่ครบ ขนาดไฟล์ไม่ตรงกับ Release")
        if digest.hexdigest() != update.sha256:
            raise UpdateError("ตรวจ SHA-256 ไม่ผ่าน ไฟล์อัปเดตอาจไม่สมบูรณ์")
        os.replace(part_path, destination)
        if progress:
            progress(100)
        return destination
    except UpdateError:
        raise
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"ดาวน์โหลดอัปเดตไม่ได้: {exc}") from exc
    finally:
        part_path.unlink(missing_ok=True)
