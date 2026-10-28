"""Real Qt workspace visual regression evidence (Windows CI, offscreen)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from novel_workflow.storage import ProjectRepository
from novel_workflow.models import NovelProfile
from novel_workflow.workspace_window import MainWindow


def main():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    output = Path("test-output/workspace-visuals")
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as directory:
        root = Path(directory)
        chapters = root / "chapters"
        chapters.mkdir()
        for number in range(1, 100):
            (chapters / f"{number:04d}.txt").write_text(
                f"第{number}章 标题\\n" + ("原文测试内容。\\n" * 8), encoding="utf-8")
        repo = ProjectRepository(root / "data")
        settings = repo.load_settings()
        settings.last_update_check_date = date.today().isoformat()
        repo.save_settings(settings)
        profile = NovelProfile(name="ทดสอบ Focus Workspace · 中文")
        profile.main_folder = str(root)
        repo.save_profile(profile)
        window = MainWindow(repo)
        window.show()
        ws = window.workspaces[profile.id]
        ws.editor.open_file(chapters / "0001.txt")
        screenshots = []
        for appearance in ("Dark", "Light"):
            window.settings.appearance = appearance
            window.apply_theme()
            window.resize(1440, 860)
            for page_name in ("editor", "vocabulary", "translation"):
                if page_name == "editor":
                    ws.open_editor()
                    viewport = ws.editor.tabs.currentWidget()
                elif page_name == "vocabulary":
                    page = ws._ensure_txt_vocabulary_page()
                    page.state["source_mode"] = "folder"
                    page.state["source_folder"] = str(chapters)
                    page.refresh()
                    ws.editor_content_stack.setCurrentWidget(page)
                    viewport = page.scroll
                else:
                    page = ws.open_translation_batches()
                    page.state["path"] = str(chapters)
                    page.mode.setCurrentIndex(page.mode.findData("folder"))
                    page.refresh()
                    viewport = page.scroll
                QTest.qWait(200)
                ws.set_focus_mode(False)
                app.processEvents()
                normal_width = viewport.width()
                normal_height = viewport.height()
                filename = f"{appearance.lower()}-{page_name}-normal.png"
                assert window.grab().save(str(output / filename))
                screenshots.append(filename)
                ws.set_focus_mode(True)
                app.processEvents()
                assert viewport.width() > normal_width, (page_name, viewport.width(), normal_width)
                filename = f"{appearance.lower()}-{page_name}-focus.png"
                assert window.grab().save(str(output / filename))
                screenshots.append(filename)
                print(f"{appearance} {page_name}: normal {normal_width}x{normal_height}, focus {viewport.width()}x{viewport.height()}", flush=True)
        window.resize(900, 600)
        app.processEvents()
        assert window.grab().save(str(output / "narrow-focus.png"))
        print("Saved real PySide6 workspace visual captures:", ", ".join(screenshots), flush=True)
        window.close()


if __name__ == "__main__":
    main()
