"""Novel library surface and profile navigation controls."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTabBar, QListWidget, QStyledItemDelegate, QStyle)


class LibraryCardDelegate(QStyledItemDelegate):
    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        if option.state & QStyle.State_Selected:
            option.font.setBold(True)
        option.state &= ~QStyle.State_HasFocus


class LibraryPage(QWidget):
    def __init__(self, owner, statuses):
        super().__init__(owner)
        library_layout = QVBoxLayout(self)
        library_layout.setContentsMargins(28, 24, 28, 24)
        library_layout.setSpacing(14)
        library_header = QHBoxLayout()
        library_title = QLabel("คลังนิยาย")
        library_title.setObjectName("pageTitle")
        library_header.addWidget(library_title, 1)
        owner.library_search = QLineEdit()
        owner.library_search.setObjectName("librarySearch")
        owner.library_search.setPlaceholderText("ค้นหานิยาย…")
        owner.library_search.setMaximumWidth(340)
        owner.library_search.textChanged.connect(owner.filter_profiles)
        library_header.addWidget(owner.library_search)
        add_story = QPushButton("＋ เพิ่มนิยาย")
        add_story.setObjectName("primaryButton")
        add_story.clicked.connect(owner.new_profile)
        library_header.addWidget(add_story)
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
        owner.profile_cards = QListWidget()
        owner.profile_cards.setItemDelegate(LibraryCardDelegate(owner.profile_cards))
        owner.profile_cards.setObjectName("novelLibrary")
        owner.profile_cards.setViewMode(QListWidget.IconMode)
        owner.profile_cards.setFlow(QListWidget.LeftToRight)
        owner.profile_cards.setWrapping(True)
        owner.profile_cards.setResizeMode(QListWidget.Adjust)
        owner.profile_cards.setMovement(QListWidget.Static)
        owner.profile_cards.setSpacing(18)
        owner.profile_cards.setIconSize(QSize(148, 188))
        owner.profile_cards.setGridSize(QSize(238, 360))
        owner.profile_cards.setWordWrap(False)
        owner.profile_cards.setTextElideMode(Qt.ElideRight)
        owner.profile_cards.itemClicked.connect(owner._open_profile_card)
        library_layout.addWidget(owner.profile_cards, 1)
        owner.library_empty_label = QLabel()
        owner.library_empty_label.setObjectName("mutedLabel")
        owner.library_empty_label.setAlignment(Qt.AlignCenter)
        owner.library_empty_label.hide()
        library_layout.addWidget(owner.library_empty_label, 1)
        self.cards = owner.profile_cards
        self.search = owner.library_search
