import sys
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from .storage import ProjectRepository
from .workspace_window import MainWindow


def _icon_path():
    return Path(__file__).resolve().parent / "resources" / "novelworkflow.png"


def _configure_font(app: QApplication):
    """Use Windows fonts with strong Thai coverage and antialiased rendering."""
    families = set(QFontDatabase.families())
    preferred = [
        "Segoe UI Variable Text",
        "Leelawadee UI",
        "Segoe UI",
        "Tahoma",
    ]
    chosen = [name for name in preferred if name in families]

    font = QFont()
    if chosen:
        font.setFamilies(chosen)
    font.setPointSizeF(10.5)
    try:
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    except AttributeError:
        pass
    app.setFont(font)


def _create_app(argv):
    app = QApplication(argv)
    app.setApplicationName("NovelWorkflow")
    app.setOrganizationName("NovelWorkflow")
    _configure_font(app)
    icon = _icon_path()
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    return app


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--import-launcher":
        app = _create_app([sys.argv[0]])
        try:
            if len(sys.argv) != 3:
                raise ValueError("ต้องระบุที่อยู่ไฟล์ config.json ของ Novel-Launcher")
            result = ProjectRepository().import_launcher_config(sys.argv[2])
            QMessageBox.information(
                None,
                "NovelWorkflow",
                f"นำเข้าข้อมูลเรียบร้อย\nโปรไฟล์ใหม่ {result['profiles']} รายการ\n"
                f"กลุ่มใหม่ {result['groups']} กลุ่ม\n"
                f"รายการเปิดไฟล์ใหม่ {result['launch_targets']} รายการ",
            )
            return 0
        except Exception as exc:
            QMessageBox.critical(None, "นำเข้าข้อมูลไม่สำเร็จ", str(exc))
            return 2

    app = _create_app(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
