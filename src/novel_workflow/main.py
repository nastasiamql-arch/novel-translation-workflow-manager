import sys
from PySide6.QtWidgets import QApplication
from .ui import MainWindow

def main():
    app=QApplication(sys.argv)
    app.setApplicationName("NovelWorkflow")
    app.setOrganizationName("NovelWorkflow")
    window=MainWindow()
    window.show()
    return app.exec()
if __name__=="__main__": raise SystemExit(main())
