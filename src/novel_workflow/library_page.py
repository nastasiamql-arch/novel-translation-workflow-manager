"""Novel library surface and profile navigation controls."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabBar, QListWidget, QStyledItemDelegate, QStyle, QComboBox, QMenu)


from .profile_list import ReorderableProfileList, ProfileItemDelegate as LibraryCardDelegate


class LibraryPage(QWidget):
    def __init__(self, owner, statuses):
        super().__init__(owner)
        library_layout = QVBoxLayout(self)
        library_layout.setContentsMargins(20, 16, 20, 16)
        library_layout.setSpacing(16)
        library_header = QVBoxLayout()
        title_row = QHBoxLayout()
        filters_row = QHBoxLayout()
        library_title = QLabel("คลังนิยาย")
        library_title.setObjectName("pageTitle")
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(library_title)
        subtitle = QLabel("เลือกนิยายเพื่อเข้าสู่พื้นที่ทำงาน")
        subtitle.setObjectName("librarySubtitle")
        heading.addWidget(subtitle)
        title_row.addLayout(heading, 1)
        owner.library_search = QLineEdit()
        owner.library_search.setObjectName("librarySearch")
        owner.library_search.setPlaceholderText("ค้นหานิยาย…")
        owner.library_search.setMaximumWidth(420)
        owner.library_search.textChanged.connect(owner.filter_profiles)
        filters_row.addWidget(owner.library_search, 1)
        owner.library_group_filter = QComboBox()
        owner.library_group_filter.setObjectName("libraryGroupFilter")
        owner.library_group_filter.setAccessibleName("กรองคลังนิยายตามกลุ่ม")
        owner.library_group_filter.setMinimumWidth(110)
        owner.library_group_filter.addItem("ทุกกลุ่ม", None)
        filters_row.addWidget(owner.library_group_filter)
        manage_groups = QPushButton("จัดการกลุ่ม")
        manage_groups.clicked.connect(owner.groups_dialog)
        filters_row.addWidget(manage_groups)
        statistics = QPushButton("สถิติ")
        statistics.clicked.connect(owner.translation_dashboard)
        filters_row.addWidget(statistics)
        add_story = QPushButton("＋ เพิ่มนิยาย")
        add_story.setObjectName("primaryButton")
        add_story.clicked.connect(owner.new_profile)
        title_row.addWidget(add_story)
        library_header.addLayout(title_row)
        library_header.addLayout(filters_row)
        library_layout.addLayout(library_header)
        owner.library_status_tabs = QTabBar()
        owner.library_status_tabs.setObjectName("libraryStatusTabs")
        owner.library_status_tabs.setAccessibleName("หมวดนิยาย")
        owner.library_status_tabs.setMovable(False)
        for status, label in statuses:
            index = owner.library_status_tabs.addTab(f"{label} (0)")
            owner.library_status_tabs.setTabData(index, status)
        owner.library_status_tabs.currentChanged.connect(
            lambda _index: owner.filter_profiles(owner.library_search.text())
        )
        library_layout.addWidget(owner.library_status_tabs)
        owner.profile_cards = ReorderableProfileList()
        owner.profile_cards.orderChanged.connect(owner._persist_profile_order)
        owner.library_group_filter.currentIndexChanged.connect(
            lambda _index: owner.filter_profiles(owner.library_search.text())
        )
        owner.profile_cards.setItemDelegate(LibraryCardDelegate(owner.profile_cards))
        owner.profile_cards.setObjectName("novelLibrary")
        owner.profile_cards.setViewMode(QListWidget.IconMode)
        owner.profile_cards.setFlow(QListWidget.LeftToRight)
        owner.profile_cards.setWrapping(True)
        owner.profile_cards.setResizeMode(QListWidget.Adjust)
        owner.profile_cards.setMovement(QListWidget.Static)
        owner.profile_cards.setDragEnabled(True)
        owner.profile_cards.setAcceptDrops(True)
        owner.profile_cards.setSpacing(18)
        owner.profile_cards.setIconSize(QSize(156, 208))
        owner.profile_cards.setGridSize(QSize(210, 292))
        owner.profile_cards.setWordWrap(True)
        owner.profile_cards.setUniformItemSizes(True)
        owner.profile_cards.setTextElideMode(Qt.ElideRight)
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
                owner.open_story_planner(profile_id)
            ))
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
            lambda row: owner._open_profile_card(owner.profile_cards.item(row)) if row >= 0 else None)
        library_layout.addWidget(owner.profile_cards, 1)
        owner.library_empty_label = QLabel()
        owner.library_empty_label.setObjectName("mutedLabel")
        owner.library_empty_label.setAlignment(Qt.AlignCenter)
        owner.library_empty_label.hide()
        library_layout.addWidget(owner.library_empty_label, 1)
        self.cards = owner.profile_cards
        self.search = owner.library_search
