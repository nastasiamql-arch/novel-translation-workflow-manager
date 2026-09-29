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
    def is_vscode_target(entry: LaunchTarget) -> bool:
        """Recognize common VS Code executable names without matching other editors."""
        # Launcher targets can come from imported configuration with surrounding
        # quotes, and the official Insiders installer uses "Code - Insiders.exe".
        target = entry.target.strip().strip('"').strip("'")
        executable = target.replace("\\", "/").rsplit("/", 1)[-1].casefold()
        return entry.kind == "application" and executable in {
            "code.exe", "code.cmd", "code.bat", "code",
            "code-insiders.exe", "code-insiders.cmd", "code-insiders.bat",
            "code-insiders", "code - insiders.exe", "code - insiders.cmd",
            "code - insiders.bat", "visual studio code.exe",
            "visual studio code.cmd", "visual studio code.bat",
        }

    @staticmethod
    def normalized_vscode_arguments(arguments: list[str]) -> list[str]:
        """Remove window reuse flags and ensure exactly one new-window flag."""
        normalized = [arg for arg in arguments if arg.casefold() not in ("-r", "--reuse-window", "-n", "--new-window")]
        normalized.append("--new-window")
        return normalized

    @classmethod
    def build_vscode_command(
        cls, target: LaunchTarget, main_folder: str | None, files: list[LaunchTarget]
    ) -> list[str]:
        command = [target.target, *cls.normalized_vscode_arguments(target.arguments)]
        if main_folder:
            command.append(main_folder)
        command.extend(entry.target for entry in files)
        return command

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
        enabled_targets = sorted(
            (entry for entry in profile.launch_targets if entry.enabled),
            key=lambda entry: entry.order,
        )
        vscode_targets = [entry for entry in enabled_targets if self.is_vscode_target(entry)]
        if not vscode_targets:
            return [self.launch_target(entry) for entry in self.build_plan(profile)]

        primary = vscode_targets[0]
        main_folder = Path(profile.main_folder).expanduser() if profile.main_folder.strip() else None
        folder_arg = str(main_folder) if main_folder and main_folder.is_dir() else None
        files = [entry for entry in enabled_targets if entry.kind == "file"]
        launchable_files = []
        results = []
        if main_folder and not main_folder.is_dir():
            results.append((False, f"โฟลเดอร์หลัก: ไม่พบโฟลเดอร์: {main_folder}"))
        for entry in files:
            path = Path(entry.target).expanduser()
            if path.is_file():
                launchable_files.append(entry)
            else:
                results.append((False, f"{entry.label or entry.target}: ไม่พบไฟล์: {path}"))

        try:
            executable = Path(primary.target).expanduser()
            if not executable.is_file():
                raise FileNotFoundError(f"ไม่พบโปรแกรม: {executable}")
            subprocess.Popen(self.build_vscode_command(primary, folder_arg, launchable_files), shell=False)
            results.append((True, primary.label or primary.target))
        except Exception as exc:
            results.append((False, f"{primary.label or primary.target}: {exc}"))

        # The profile's implicit folder and bundled files were consumed by VS Code.
        # Explicit folder targets and every other application/site keep their behavior.
        for entry in enabled_targets:
            if entry is primary or entry.kind == "file":
                continue
            results.append(self.launch_target(entry))
        return results

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
