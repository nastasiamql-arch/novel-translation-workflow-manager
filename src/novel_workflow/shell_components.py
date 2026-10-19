"""Reusable shell components with content-driven geometry."""
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel, QToolButton, QSizePolicy, QStackedWidget, QProgressBar
from PySide6.QtGui import QFontMetrics, QPixmap
from pathlib import Path
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
    def __init__(self, repo=None):
        super().__init__()
        self.repo = repo
        self.setObjectName('novelHeader')
        layout = QHBoxLayout(self); layout.setContentsMargins(12,8,12,8); layout.setSpacing(10)
        self.cover = QLabel(); self.cover.setObjectName('activeNovelCover')
        self.cover.setFixedSize(44, 58); self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setAccessibleName('ปกนิยายที่กำลังทำงาน')
        layout.addWidget(self.cover)
        text = QVBoxLayout(); text.setSpacing(3)
        self.title = ElidingLabel(); self.title.setObjectName('sectionHeading')
        self.title.setMinimumWidth(0); self.title.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        self.progress = QLabel(); self.progress.setWordWrap(True)
        self.progress.setObjectName('completedTranslationSummary')
        self.progress.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.title); text.addWidget(self.progress)
        # Keep the per-novel translation goal visible without consuming editor space.
        goal_row = QHBoxLayout()
        goal_row.setContentsMargins(0, 0, 0, 0)
        goal_row.setSpacing(7)
        self.goal_label = QLabel("ยังไม่ได้ตั้งเป้าหมาย")
        self.goal_label.setObjectName("novelGoalLabel")
        self.goal_label.setMinimumWidth(0)
        self.goal_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.goal_bar = QProgressBar()
        self.goal_bar.setObjectName("novelGoalProgress")
        self.goal_bar.setRange(0, 100)
        self.goal_bar.setTextVisible(False)
        self.goal_bar.setFixedSize(88, 7)
        self.goal_edit = QToolButton()
        self.goal_edit.setObjectName("novelGoalEdit")
        self.goal_edit.setText("ตั้งเป้า")
        self.goal_edit.setCursor(Qt.PointingHandCursor)
        self.goal_edit.setAccessibleName("ตั้งหรือแก้เป้าหมายการแปลของนิยายเรื่องนี้")
        self.goal_reset = QToolButton()
        self.goal_reset.setObjectName("novelGoalReset")
        self.goal_reset.setText("รีเซ็ต")
        self.goal_reset.setCursor(Qt.PointingHandCursor)
        self.goal_reset.setAccessibleName("รีเซ็ตความคืบหน้าเป้าหมายของนิยายเรื่องนี้")
        goal_row.addWidget(self.goal_label, 1)
        goal_row.addWidget(self.goal_bar)
        goal_row.addWidget(self.goal_edit)
        goal_row.addWidget(self.goal_reset)
        text.addLayout(goal_row)
        layout.addLayout(text, 1)
        self.close_button = QToolButton(); self.close_button.setText('×')
        self.close_button.setAccessibleName('ปิดเรื่องที่กำลังทำงาน')
        self.close_button.setToolTip('ปิดเรื่องนี้และกลับคลังนิยาย')
        layout.addWidget(self.close_button, 0, Qt.AlignTop)

    def refresh(self, profile, chapter=None):
        from .translation_progress import daily_chapter_count, completion_label, completion_tooltip
        self.title.setText(profile.name)
        self.cover.setToolTip(profile.name)
        cover_key = (profile.id, profile.cover_image_path)
        if getattr(self, "_cover_key", None) != cover_key:
            self._cover_key = cover_key
            self._render_cover(profile)
        today = daily_chapter_count(profile)
        today_text = f'วันนี้ +{today:,} บท' if today else 'วันนี้ 0 บท'
        self.progress.setText(f'{completion_label(profile)}  ·  {today_text}')
        self.progress.setToolTip(completion_tooltip(profile))
        from .translation_progress import goal_progress
        goal = goal_progress(profile)
        self.goal_bar.setVisible(goal is not None)
        self.goal_reset.setVisible(goal is not None)
        self.goal_edit.setText("แก้เป้า" if goal else "ตั้งเป้า")
        if goal:
            completed, target, percentage = goal
            extra = completed - target
            suffix = f" ✓ · เกิน +{extra} บท" if extra > 0 else (" ✓" if completed == target else "")
            self.goal_label.setText(f"เป้าหมาย {completed}/{target} บท · {percentage}%{suffix}")
            self.goal_label.setToolTip(f"{profile.name}: แปลสำเร็จ {completed} จากเป้าหมาย {target} บท{suffix}")
            self.goal_bar.setValue(percentage)
            finished = completed >= target
            if self.goal_bar.property("goalComplete") != finished:
                self.goal_bar.setProperty("goalComplete", finished)
                self.goal_bar.style().unpolish(self.goal_bar)
                self.goal_bar.style().polish(self.goal_bar)
        else:
            self.goal_label.setText("ยังไม่ได้ตั้งเป้าหมายการแปล")
            self.goal_label.setToolTip("กด ตั้งเป้า เพื่อกำหนดจำนวนบทของนิยายเรื่องนี้")

    def _render_cover(self, profile):
        """Cover decoding is keyed by profile, never by document cursor position."""
        self.cover.setProperty('coverPath', '')
        image = QPixmap()
        if self.repo and profile.cover_image_path:
            try:
                path = self.repo.resolve_project_path(profile.id, profile.cover_image_path)
                image = QPixmap(str(path)) if path.is_file() else QPixmap()
                if not image.isNull():
                    self.cover.setProperty('coverPath', str(path.resolve()))
            except (OSError, ValueError):
                pass
        if image.isNull():
            image = QPixmap(str(Path(__file__).parent / 'resources' / 'novelworkflow.png'))
        if image.isNull():
            self.cover.setText('▤')
        else:
            self.cover.setPixmap(image.scaled(self.cover.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))


class NavigationSidebar(QFrame):
    """Readable navigation that can collapse to icon-only mode."""
    selected = Signal(str)
    collapsedChanged = Signal(bool)

    def __init__(self, collapsed=False):
        super().__init__()
        self.setObjectName('navigationSidebar')
        self.buttons = {}
        self.labels = {}
        self.collapsed = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        layout.setSpacing(6)

        self.brand_toggle = QToolButton(self)
        self.brand_toggle.setObjectName('navigationBrand')
        self.brand_toggle.setAccessibleName('ย่อหรือขยายเมนูหลัก')
        self.brand_toggle.setCursor(Qt.PointingHandCursor)
        self.brand_toggle.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        layout.addWidget(self.brand_toggle)
        layout.addSpacing(14)

        for key, icon, title in [
            ('library', '▦', 'คลังนิยาย'),
            ('workspace', '▤', 'กำลังทำงาน'),
            ('progress', '◷', 'สถิติ'),
            ('groups', '▧', 'กลุ่มนิยาย'),
            ('settings', '⚙', 'ตั้งค่า'),
        ]:
            if key == 'settings':
                layout.addStretch(1)
            button = QToolButton(self)
            button.setCheckable(True)
            button.setObjectName('navigationItem')
            button.setText(title)
            button.setIconSize(QSize(20, 20))
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setCursor(Qt.PointingHandCursor)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            button.clicked.connect(lambda checked=False, name=key: self.selected.emit(name))
            self.buttons[key] = button
            self.labels[key] = (icon, title)
            layout.addWidget(button)
        self.set_collapsed(bool(collapsed), notify=False)
        self.refresh_icons('Light')

    def set_collapsed(self, collapsed, *, notify=True):
        collapsed = bool(collapsed)
        if self.collapsed == collapsed:
            return
        self.collapsed = collapsed
        self.setFixedWidth(60 if collapsed else 196)
        self.brand_toggle.setText('☰' if collapsed else '☰   VALHALLA')
        self.brand_toggle.setToolTip('ขยายเมนู' if collapsed else 'ย่อเมนู')
        for button in self.buttons.values():
            button.setToolButtonStyle(
                Qt.ToolButtonIconOnly if collapsed else Qt.ToolButtonTextBesideIcon
            )
        if notify:
            self.collapsedChanged.emit(collapsed)

    def refresh_icons(self, appearance):
        for key, button in self.buttons.items():
            button.setIcon(navigation_icon(key, theme_colors(appearance)))

    def select(self, key):
        for name, button in self.buttons.items():
            button.setChecked(name == key)

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
