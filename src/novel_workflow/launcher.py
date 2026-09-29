from __future__ import annotations

import os
import subprocess
import webbrowser
import ctypes
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
    def default_open_application(target: str) -> Path | None:
        """Return Windows' registered open handler for a file, if available."""
        if os.name != "nt":
            return None
        extension = Path(target).suffix
        if not extension:
            return None
        try:
            query = ctypes.WinDLL("Shlwapi.dll").AssocQueryStringW
            query.argtypes = [
                ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
                ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint),
            ]
            query.restype = ctypes.c_long
            length = ctypes.c_uint(0)
            query(0, 2, extension, "open", None, ctypes.byref(length))
            if not length.value:
                return None
            buffer = ctypes.create_unicode_buffer(length.value)
            if query(0, 2, extension, "open", buffer, ctypes.byref(length)) != 0:
                return None
            return Path(buffer.value).expanduser()
        except (AttributeError, OSError, ValueError):
            return None

    @classmethod
    def vscode_association_launch(
        cls, files: list[LaunchTarget]
    ) -> tuple[LaunchTarget | None, list[LaunchTarget]]:
        """Find files whose actual Windows open handler is VS Code."""
        for entry in files:
            application = cls.default_open_application(entry.target)
            if application is None:
                continue
            candidate = LaunchTarget(
                label="Visual Studio Code", kind="application", target=str(application)
            )
            if not cls.is_vscode_target(candidate):
                continue
            primary_path = os.path.normcase(os.path.abspath(application))
            grouped_files = []
            for file_entry in files:
                handler = cls.default_open_application(file_entry.target)
                if handler and os.path.normcase(os.path.abspath(handler)) == primary_path:
                    grouped_files.append(file_entry)
            return candidate, grouped_files
        return None, []

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
            enabled_files = [entry for entry in enabled_targets if entry.kind == "file"]
            primary, launchable_files = self.vscode_association_launch(enabled_files)
            if primary is None:
                return [self.launch_target(entry) for entry in self.build_plan(profile)]
        else:
            primary = vscode_targets[0]
            launchable_files = [entry for entry in enabled_targets if entry.kind == "file"]
        grouped_file_ids = {entry.id for entry in launchable_files}

        main_folder = Path(profile.main_folder).expanduser() if profile.main_folder.strip() else None
        folder_arg = str(main_folder) if main_folder and main_folder.is_dir() else None
        results = []
        if main_folder and not main_folder.is_dir():
            results.append((False, f"โฟลเดอร์หลัก: ไม่พบโฟลเดอร์: {main_folder}"))
        for entry in launchable_files:
            path = Path(entry.target).expanduser()
            if path.is_file():
                continue
            else:
                results.append((False, f"{entry.label or entry.target}: ไม่พบไฟล์: {path}"))
        launchable_files = [
            entry for entry in launchable_files if Path(entry.target).expanduser().is_file()
        ]

        try:
            executable = Path(primary.target).expanduser()
            if not executable.is_file():
                raise FileNotFoundError(f"ไม่พบโปรแกรม: {executable}")
            subprocess.Popen(self.build_vscode_command(primary, folder_arg, launchable_files), shell=False)
            results.append((True, primary.label or primary.target))
        except Exception as exc:
            results.append((False, f"{primary.label or primary.target}: {exc}"))

        # The main folder is also a user-facing File Explorer target. VS Code
        # receives it as the workspace while Explorer shows the folder itself.
        if folder_arg:
            results.append(self.launch_target(LaunchTarget(
                label="โฟลเดอร์หลัก", kind="folder", target=folder_arg
            )))

        # The bundled files were consumed by VS Code. Explicit folder targets and
        # every other application/site keep their existing behavior.
        for entry in enabled_targets:
            if entry is primary or entry.id in grouped_file_ids:
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
