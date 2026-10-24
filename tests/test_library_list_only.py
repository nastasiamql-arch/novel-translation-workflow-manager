"""Library-only list UI, legacy preference and profile-data preservation."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from datetime import date

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QListWidget, QPushButton

from novel_workflow.models import NovelProfile
from novel_workflow.storage import ProjectRepository
from novel_workflow.workspace_window import MainWindow


@pytest.fixture
def library(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    repo = ProjectRepository(tmp_path / "data")
    settings = repo.load_settings()
    settings.library_view_mode = "gallery"  # Existing users' old preference.
    settings.last_update_check_date = date.today().isoformat()
    repo.save_settings(settings)

    for name in ("นิยายเรื่องแรก", "นิยายเรื่องที่สอง", "นิยายเรื่องที่สาม"):
        repo.save_profile(NovelProfile(name=name, status="translating"))
    profiles = repo.list_profiles()
    cover_file = repo.profile_dir(profiles[0].id) / "cover.png"
    image = QPixmap(96, 128)
    image.fill(QColor("#446688"))
    assert image.save(str(cover_file))
    profiles[0].cover_image_path = "cover.png"
    repo.save_profile(profiles[0])

    before_profiles = [(p.id, p.name, p.cover_image_path)
                       for p in repo.list_profiles()]
    before_cover = cover_file.read_bytes()
    window = MainWindow(repo)
    window.show_library()
    app.processEvents()
    try:
        yield window, repo, before_profiles, cover_file, before_cover, app
    finally:
        window.close()
        app.processEvents()


def test_library_always_opens_in_list_and_has_no_gallery_toggle(library):
    window, repo, before_profiles, cover_file, before_cover, app = library
    cards = window.profile_cards
    assert cards.viewMode() == QListWidget.ListMode
    assert cards.flow() == QListWidget.TopToBottom
    assert not cards.isWrapping()
    assert window.settings.library_view_mode == "list"
    assert not hasattr(window, "library_gallery_view")
    assert not hasattr(window, "library_list_view")
    assert not window.findChildren(QPushButton, "libraryViewButton")
    assert repo.load_settings().library_view_mode == "gallery"

    window.navigate("library")
    app.processEvents()
    assert cards.viewMode() == QListWidget.ListMode
    assert [(p.id, p.name, p.cover_image_path)
            for p in repo.list_profiles()] == before_profiles
    assert cover_file.read_bytes() == before_cover


def test_list_keeps_search_selection_reordering_and_novel_open(library):
    window, repo, before_profiles, cover_file, before_cover, app = library
    cards = window.profile_cards
    original_ids = [p[0] for p in before_profiles]
    assert [cards.item(i).data(Qt.UserRole)
            for i in range(cards.count())] == original_ids

    cards.setCurrentRow(1)
    assert cards.currentItem().data(Qt.UserRole) == original_ids[1]
    window.library_search.setText("เรื่องที่สอง")
    app.processEvents()
    visible = [cards.item(i).data(Qt.UserRole) for i in range(cards.count())
               if not cards.item(i).isHidden()]
    assert visible == [original_ids[1]]
    window.library_search.clear()
    app.processEvents()

    desired_order = list(reversed(original_ids))
    window._persist_profile_order(desired_order)
    assert [p.id for p in repo.list_profiles()] == desired_order
    window.refresh_profiles()
    window.show_library()
    app.processEvents()
    assert [cards.item(i).data(Qt.UserRole) for i in range(cards.count())] == desired_order

    window._open_profile_card(cards.item(0))
    app.processEvents()
    assert window.profile.id == desired_order[0]
    assert cards.viewMode() == QListWidget.ListMode
    assert {p.id: (p.name, p.cover_image_path) for p in repo.list_profiles()} == {
        id_: (name, cover) for id_, name, cover in before_profiles}
    assert cover_file.read_bytes() == before_cover
