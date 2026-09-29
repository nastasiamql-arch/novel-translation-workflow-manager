import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from .storage import ProjectRepository
from .workspace_window import MainWindow

def _icon_path():
    return Path(__file__).resolve().parent / "resources" / "novelworkflow.png"

def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--import-launcher":
        app = QApplication([sys.argv[0]])
        app.setApplicationName("NovelWorkflow")
        icon = _icon_path()
        if icon.is_file(): app.setWindowIcon(QIcon(str(icon)))
        try:
            if len(sys.argv) != 3:
                raise ValueError("ต้องระบุที่อยู่ไฟล์ config.json ของ Novel-Launcher")
            result = ProjectRepository().import_launcher_config(sys.argv[2])
            QMessageBox.information(None, "NovelWorkflow",
                f"นำเข้าข้อมูลเรียบร้อย\nโปรไฟล์ใหม่ {result['profiles']} รายการ\nกลุ่มใหม่ {result['groups']} กลุ่ม\nรายการเปิดไฟล์ใหม่ {result['launch_targets']} รายการ")
            return 0
        except Exception as exc:
            QMessageBox.critical(None, "นำเข้าข้อมูลไม่สำเร็จ", str(exc))
            return 2
    app = QApplication(sys.argv)
    app.setApplicationName("NovelWorkflow")
    app.setOrganizationName("NovelWorkflow")
    icon = _icon_path()
    if icon.is_file(): app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
