"""Modern novel library: one ordered model, two responsive presentations."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTabBar, QListWidget, QComboBox, QMenu,
)

from .profile_list import ReorderableProfileList, ProfileItemDelegate as LibraryCardDelegate


class CompactLibraryTabBar(QTabBar):
    """Keep status labels intact at every selected state and font scale."""

    def tabSizeHint(self, index):
        size = super().tabSizeHint(index)
        selected_font = QFont(self.font())
        selected_font.setBold(True)
        metrics = QFontMetrics(selected_font)
        # Qt styles may measure an unselected (lighter) font. Reserve the
        # selected label width plus both paddings, margins and a border.
        size.setWidth(max(size.width(), metrics.horizontalAdvance(
            self.tabText(index)) + 48))
        size.setHeight(max(size.height(), metrics.height() + 24, 44))
        return size

    def minimumTabSizeHint(self, index):
        # Never elide a Thai status or the final closing parenthesis.
        return self.tabSizeHint(index)


class LibraryPage(QWidget):
    def __init__(self, owner, statuses):
        super().__init__(owner)
        library_layout = QVBoxLayout(self)
        library_layout.setContentsMargins(24, 20, 24, 20)
        library_layout.setSpacing(15)

        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        heading = QVBoxLayout()
        heading.setSpacing(5)
        title = QLabel("คลังนิยาย")
        title.setObjectName("pageTitle")
        subtitle = QLabel("จัดการนิยายและติดตามงานแปลของคุณ")
        subtitle.setObjectName("librarySubtitle")
        heading.addWidget(title)
        heading.addWidget(subtitle)
        title_row.addLayout(heading, 1)
        add_story = QPushButton("＋ เพิ่มนิยาย")
        add_story.setObjectName("primaryButton")
        add_story.clicked.connect(owner.new_profile)
        title_row.addWidget(add_story, 0, Qt.AlignTop)
        library_layout.addLayout(title_row)

        filters_row = QHBoxLayout()
        filters_row.setSpacing(10)
        owner.library_search = QLineEdit()
        owner.library_search.setObjectName("librarySearch")
        owner.library_search.setAccessibleName("ค้นหาชื่อนิยาย")
        owner.library_search.setPlaceholderText("ค้นหาชื่อนิยาย…")
        owner.library_search.setClearButtonEnabled(True)
        owner.library_search.setMaximumWidth(440)
        owner.library_search.setMinimumWidth(150)
        owner.library_search.textChanged.connect(owner.filter_profiles)
        filters_row.addWidget(owner.library_search, 1)

        owner.library_group_filter = QComboBox()
        owner.library_group_filter.setObjectName("libraryGroupFilter")
        owner.library_group_filter.setAccessibleName("กรองคลังนิยายตามกลุ่ม")
        owner.library_group_filter.setMinimumWidth(115)
        owner.library_group_filter.addItem("ทุกกลุ่ม", None)
        filters_row.addWidget(owner.library_group_filter)
        manage_groups = QPushButton("จัดการกลุ่ม")
        manage_groups.clicked.connect(owner.groups_dialog)
        filters_row.addWidget(manage_groups)
        statistics = QPushButton("สถิติ")
        statistics.clicked.connect(owner.translation_dashboard)
        filters_row.addWidget(statistics)
        library_layout.addLayout(filters_row)

        owner.library_status_tabs = CompactLibraryTabBar()
        owner.library_status_tabs.setObjectName("libraryStatusTabs")
        owner.library_status_tabs.setAccessibleName("หมวดนิยาย")
        owner.library_status_tabs.setMovable(False)
        owner.library_status_tabs.setExpanding(False)
        owner.library_status_tabs.setUsesScrollButtons(True)
        owner.library_status_tabs.setElideMode(Qt.ElideNone)
        owner.library_status_tabs.setFocusPolicy(Qt.StrongFocus)
        for status, label in statuses:
            index = owner.library_status_tabs.addTab(f"{label} (0)")
            owner.library_status_tabs.setTabData(index, status)
        owner.library_status_tabs.currentChanged.connect(
            lambda _index: owner.filter_profiles(owner.library_search.text()))
        status_row = QHBoxLayout()
        status_row.setContentsMargins(6, 0, 6, 0)
        status_row.addWidget(owner.library_status_tabs, 0)
        status_row.addStretch(1)
        library_layout.addLayout(status_row)

        gallery_header = QHBoxLayout()
        owner.library_section_title = QLabel("กำลังแปล")
        owner.library_section_title.setObjectName("librarySectionTitle")
        gallery_header.addWidget(owner.library_section_title)
        owner.library_section_count = QLabel("0 เรื่อง")
        owner.library_section_count.setObjectName("librarySectionCount")
        gallery_header.addWidget(owner.library_section_count)
        gallery_header.addStretch(1)

        owner.library_gallery_view = QPushButton("▦ มุมมองปก")
        owner.library_gallery_view.setObjectName("libraryViewButton")
        owner.library_gallery_view.setCheckable(True)
        owner.library_gallery_view.setAccessibleName("แสดงคลังนิยายแบบปก")
        owner.library_list_view = QPushButton("☷ มุมมองรายการ")
        owner.library_list_view.setObjectName("libraryViewButton")
        owner.library_list_view.setCheckable(True)
        owner.library_list_view.setAccessibleName("แสดงคลังนิยายแบบรายการ")
        gallery_header.addWidget(owner.library_gallery_view)
        gallery_header.addWidget(owner.library_list_view)
        library_layout.addLayout(gallery_header)

        owner.profile_cards = ReorderableProfileList()
        owner.profile_cards.orderChanged.connect(owner._persist_profile_order)
        owner.profile_cards.setObjectName("novelLibrary")
        delegate = LibraryCardDelegate(owner.profile_cards)
        owner.profile_cards.setItemDelegate(delegate)
        owner.profile_cards.setIconSize(QSize(222, 296))
        owner.profile_cards.setUniformItemSizes(True)
        owner.profile_cards.setWordWrap(True)
        owner.profile_cards.setTextElideMode(Qt.ElideRight)
        owner.profile_cards.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        owner.profile_cards.setAccessibleName("รายการนิยายในคลัง")

        def set_view(mode, save=True):
            mode = "list" if mode == "list" else "gallery"
            owner.profile_cards.set_library_view(mode)
            owner.library_gallery_view.setChecked(mode == "gallery")
            owner.library_list_view.setChecked(mode == "list")
            if save and owner.settings.library_view_mode != mode:
                owner.settings.library_view_mode = mode
                owner.repo.save_settings(owner.settings)

        owner.library_gallery_view.clicked.connect(lambda: set_view("gallery"))
        owner.library_list_view.clicked.connect(lambda: set_view("list"))
        set_view(getattr(owner.settings, "library_view_mode", "gallery"), save=False)

        owner.library_group_filter.currentIndexChanged.connect(
            lambda _index: owner.filter_profiles(owner.library_search.text()))
        owner.profile_cards.setContextMenuPolicy(Qt.CustomContextMenu)

        def show_card_menu(point):
            card = owner.profile_cards.itemAt(point)
            if card is None:
                return
            profile_id = card.data(Qt.UserRole)
            menu = QMenu(owner.profile_cards)
            menu.addAction("เปิดนิยาย", lambda: owner.open_planned_novel(profile_id))
            menu.addAction("แผนการแปล", lambda: (
                owner.open_planned_novel(profile_id),
                owner.open_story_planner(profile_id)))
            menu.addSeparator()

            def with_selected(callback):
                owner.open_planned_novel(profile_id)
                if owner.profile and owner.profile.id == profile_id:
                    callback()

            menu.addAction("เปลี่ยนชื่อ", lambda: with_selected(owner.rename_profile))
            menu.addAction("เปลี่ยนปก", lambda: with_selected(owner.set_cover))
            menu.addAction("ลบนิยาย…", lambda: with_selected(owner.delete_profile))
            menu.exec(owner.profile_cards.viewport().mapToGlobal(point))

        owner.profile_cards.customContextMenuRequested.connect(show_card_menu)
        owner.profile_cards.selectionCommitted.connect(
            lambda row: owner._open_profile_card(owner.profile_cards.item(row))
            if row >= 0 else None)
        library_layout.addWidget(owner.profile_cards, 1)

        empty_box = QWidget()
        empty_layout = QVBoxLayout(empty_box)
        empty_layout.setContentsMargins(16, 32, 16, 32)
        empty_layout.setSpacing(12)
        empty_layout.addStretch(1)
        owner.library_empty_label = QLabel()
        owner.library_empty_label.setObjectName("libraryEmptyTitle")
        owner.library_empty_label.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(owner.library_empty_label)
        owner.library_empty_hint = QLabel()
        owner.library_empty_hint.setObjectName("librarySubtitle")
        owner.library_empty_hint.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(owner.library_empty_hint)
        owner.library_empty_action = QPushButton("＋ เพิ่มนิยาย")
        owner.library_empty_action.setObjectName("primaryButton")
        owner.library_empty_action.clicked.connect(
            lambda: owner.library_search.clear() if owner.library_search.text().strip()
            else owner.new_profile())
        empty_action_row = QHBoxLayout()
        empty_action_row.addStretch(1)
        empty_action_row.addWidget(owner.library_empty_action)
        empty_action_row.addStretch(1)
        empty_layout.addLayout(empty_action_row)
        empty_layout.addStretch(1)
        empty_box.hide()
        owner.library_empty_box = empty_box
        library_layout.addWidget(empty_box, 1)

        self.cards = owner.profile_cards
        self.search = owner.library_search
