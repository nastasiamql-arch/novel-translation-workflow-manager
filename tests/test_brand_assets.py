import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon, QImageReader
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]


def test_n_monogram_svg_masters_render_and_windows_icon_has_favicon_sizes():
    app = QApplication.instance() or QApplication([])
    masters = ROOT / "assets" / "brand"
    svg_files = list(masters.glob("*.svg"))
    assert len(svg_files) == 4
    assert all(QSvgRenderer(str(path)).isValid() for path in svg_files)
    assert all(
        'd="M22 30h15l26 27V30h15v40H63L37 43v27H22z"'
        in path.read_text(encoding="utf-8")
        for path in svg_files
    )
    app_icon = ROOT / "src" / "novel_workflow" / "resources" / "palantir_novel.svg"
    assert app_icon.read_bytes() == (masters / "palantir_novel_app_dark.svg").read_bytes()

    icon = QIcon(str(ROOT / "assets" / "palantir_novel.ico"))
    assert not icon.isNull()
    assert {(size.width(), size.height()) for size in icon.availableSizes()} >= {
        (16, 16), (32, 32), (48, 48), (256, 256),
    }

    exports = masters / "exports"
    for name, size in (("favicon-16.png", 16), ("favicon-32.png", 32),
                       ("favicon-48.png", 48),
                       ("palantir-novel-dark-1024.png", 1024),
                       ("palantir-novel-light-1024.png", 1024)):
        reader = QImageReader(str(exports / name))
        assert reader.size().width() == size
        assert reader.size().height() == size
