from __future__ import annotations

import os
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from .models import LaunchTarget, NovelProfile, NovelGroup

class LauncherService:
    """Launch profile folders, files, applications, and websites without shell strings."""

    @staticmethod
    def build_plan(profile: NovelProfile) -> list[LaunchTarget]:
        plan=[]
        if profile.main_folder.strip():
            plan.append(LaunchTarget(label="โฟลเดอร์หลัก",kind="folder",target=profile.main_folder,order=-1))
        plan.extend(sorted((entry for entry in profile.launch_targets if entry.enabled),key=lambda entry:entry.order))
        return plan

    @staticmethod
    def launch_target(entry: LaunchTarget) -> tuple[bool,str]:
        try:
            if entry.kind=="website":
                parsed=urlparse(entry.target)
                if parsed.scheme not in ("http","https") or not parsed.netloc:
                    raise ValueError("รองรับเฉพาะ URL แบบ http และ https")
                if not webbrowser.open(entry.target):
                    raise RuntimeError("เปิดเว็บไซต์ไม่สำเร็จ")
            elif entry.kind=="application":
                path=Path(entry.target).expanduser()
                if not path.is_file():raise FileNotFoundError(f"ไม่พบโปรแกรม: {path}")
                subprocess.Popen([str(path),*entry.arguments],shell=False)
            elif entry.kind in ("file","folder"):
                path=Path(entry.target).expanduser()
                if not path.exists():raise FileNotFoundError(f"ไม่พบไฟล์หรือโฟลเดอร์: {path}")
                if hasattr(os,"startfile"):
                    os.startfile(str(path))
                elif os.name=="posix":
                    subprocess.Popen(["xdg-open",str(path)],shell=False)
                else:
                    raise OSError("ไม่รองรับการเปิดรายการนี้บนระบบปฏิบัติการนี้")
            else:
                raise ValueError(f"ไม่รู้จักประเภท Launcher: {entry.kind}")
            return True,entry.label or entry.target
        except Exception as exc:
            return False,f"{entry.label or entry.target}: {exc}"

    def launch_profile(self,profile:NovelProfile) -> list[tuple[bool,str]]:
        return [self.launch_target(entry) for entry in self.build_plan(profile)]

    def launch_group(self,group:NovelGroup,profiles:list[NovelProfile]) -> list[tuple[bool,str]]:
        by_id={profile.id:profile for profile in profiles}
        results=[]
        for profile_id in group.profile_ids:
            profile=by_id.get(profile_id)
            if profile is None:
                results.append((False,f"ไม่พบโปรไฟล์ {profile_id} ในกลุ่ม {group.name}"))
                continue
            results.extend(self.launch_profile(profile))
        return results
