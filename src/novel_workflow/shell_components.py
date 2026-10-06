"""Reusable shell components with content-driven geometry."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QSizePolicy, QStackedWidget
from PySide6.QtGui import QFontMetrics
from .navigation_icons import navigation_icon
from .theme import theme_colors


class ElidingLabel(QLabel):
    def setText(self, text):
        self.full_text = str(text)
        self.setToolTip(self.full_text)
        self._render()

    def _render(self):
        super().setText(QFontMetrics(self.font()).elidedText(getattr(self, 'full_text', ''), Qt.ElideMiddle, max(0,self.width()-8)))

    def resizeEvent(self, event):
        super().resizeEvent(event); self._render()


class NovelHeader(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName('novelHeader')
        layout = QVBoxLayout(self); layout.setContentsMargins(12,8,12,8); layout.setSpacing(3)
        self.title = ElidingLabel(); self.title.setObjectName('sectionHeading')
        self.title.setMinimumWidth(0); self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.progress = QLabel(); self.progress.setWordWrap(True)
        self.progress.setToolTip('อ่านจาก Context; verified นับเมื่อส่งออกสำเร็จ')
        layout.addWidget(self.title); layout.addWidget(self.progress)

    def refresh(self, profile, chapter=None):
        from .translation_progress import daily_chapter_count, goal_progress
        from .export_service import daily_export_count, verified_goal_text
        self.title.setText(profile.name)
        chapter = chapter if chapter is not None else profile.chapter_state.current_chapter
        translated = f'แปลถึงบท {chapter}' if profile.context_path else 'ยังไม่ได้เลือก Context'
        goal = goal_progress(profile)
        if goal: translated += f' · เป้าหมายแปล {goal[0]}/{goal[1]} บท'
        self.progress.setText(f'{translated}  ·  วันนี้แปล +{daily_chapter_count(profile)} บท\n'
            f'วันนี้ส่ง {profile.txt_export_settings.filename} {daily_export_count(profile)} ไฟล์  ·  รอบส่ง {verified_goal_text(profile)}')


class NavigationSidebar(QFrame):
    selected = Signal(str)
    def __init__(self, collapsed=False):
        super().__init__(); self.setObjectName('navigationSidebar')
        self.buttons = {}; self.labels = {}
        # Legacy width/collapse preferences remain stored, but navigation is icon-only.
        self.collapsed = True
        self.setMinimumWidth(60); self.setMaximumWidth(60)
        layout = QVBoxLayout(self); layout.setContentsMargins(6,8,6,8)
        for key, icon, title in [('library','▦','คลังนิยาย'),('workspace','▤','กำลังทำงาน'),('progress','◷','สถิติ'),('groups','▧','กลุ่ม'),('settings','⚙','ตั้งค่า')]:
            if key == 'settings': layout.addStretch(1)
            button = QToolButton(); button.setCheckable(True); button.setObjectName('navigationItem')
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            button.setToolTip(title); button.setAccessibleName(title)
            button.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Preferred)
            button.clicked.connect(lambda checked=False,key=key:self.selected.emit(key))
            self.buttons[key]=button; self.labels[key]=(icon,title); layout.addWidget(button)
        self.refresh_icons("Light")

    def refresh_icons(self, appearance):
        for key, button in self.buttons.items():
            button.setIcon(navigation_icon(key, theme_colors(appearance)))

    def select(self, key):
        for name,button in self.buttons.items():
            button.setChecked(name==key)


class EditorToolbar(QFrame):
    """Secondary controls move into More when the editor becomes narrow."""
    def __init__(self):
        super().__init__()
        self.overflow_controls = []

    def sizeHint(self):
        return QSize(280, super().sizeHint().height())

    def minimumSizeHint(self):
        return QSize(210, super().minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for widget, threshold in self.overflow_controls:
            widget.setVisible(self.width() >= threshold)


class MainPageStack(QStackedWidget):
    """Utility-page minimums must not squeeze navigation on other pages."""
    def minimumSizeHint(self):
        return QSize(600, 420)

    def sizeHint(self):
        return QSize(1000, 650)
