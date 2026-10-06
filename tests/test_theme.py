from PySide6.QtGui import QPalette

import novel_workflow.theme as theme
from novel_workflow.theme import _DARK, _LIGHT, application_stylesheet, qt_palette


def _luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_semantic_selection_is_distinct_from_hover_and_current_line():
    for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
        assert tokens["selection"] != tokens["hover"]
        assert tokens["selection"] != tokens["surface"]
        assert theme.editor_colors(appearance)["current_line"] != tokens["selection"]
        assert _contrast(tokens["selection_text"], tokens["selection"]) >= 4.5
        assert len({tokens[key] for key in ('hover', 'item_selection', 'current_line', 'selection')}) == 4
        assert _contrast(tokens['text'], tokens['item_selection']) >= 4.5
        assert _contrast(tokens['secondary'], tokens['item_selection']) >= 4.5
        editor = theme.editor_colors(appearance)
        assert _contrast(editor['find_text'], editor['find_active']) >= 4.5


def test_line_icons_render_at_multiple_device_scales():
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from novel_workflow.navigation_icons import LineIconEngine
    app = QApplication.instance() or QApplication([])
    for tokens in (_LIGHT, _DARK):
        for name in ('library', 'workspace', 'progress', 'groups', 'settings'):
            engine = LineIconEngine(name, tokens['secondary'], tokens['disabled_text'])
            for scale in (1, 1.25, 1.5, 2):
                pixmap = engine.scaledPixmap(QSize(20, 20), QIcon.Normal, QIcon.Off, scale)
                assert pixmap.width() == round(20 * scale)
                assert pixmap.devicePixelRatio() == scale
                image = pixmap.toImage()
                assert any(image.pixelColor(x, y).alpha() for x in range(image.width()) for y in range(image.height()))


def test_theme_text_and_status_bar_meet_readable_contrast():
    for palette in (_DARK, _LIGHT):
        for background in ("app", "surface", "sidebar", "surface2"):
            assert _contrast(palette["text"], palette[background]) >= 4.5
            assert _contrast(palette["secondary"], palette[background]) >= 4.5
            assert _contrast(palette["muted"], palette[background]) >= 4.5
            assert _contrast(palette["disabled_text"], palette[background]) >= 4.5
        assert _contrast(palette["status_text"], palette["status"]) >= 4.5
        assert _contrast(palette["primary_text"], palette["primary"]) >= 4.5
        assert _contrast(palette["primary_text"], palette["primary_hover"]) >= 4.5
        for semantic_text in ("accent", "success", "warning", "danger"):
            assert _contrast(palette[semantic_text], palette["app"]) >= 4.5
            assert _contrast(palette[semantic_text], palette["surface"]) >= 4.5


def test_theme_styles_disabled_controls_and_keyboard_focus_explicitly():
    for appearance in ("Dark", "Light"):
        stylesheet = application_stylesheet(appearance)
        assert "QToolBar#mainToolbar QToolButton:disabled" in stylesheet
        assert "QFrame#editorHeader QToolButton" in stylesheet
        assert "QFrame#editorHeader QToolButton:disabled" in stylesheet
        assert "QPushButton:disabled" in stylesheet
        assert "QAbstractButton:disabled" in stylesheet
        assert 'QToolButton[keyboardFocus="true"]' in stylesheet
        assert "font-size: 12pt" in stylesheet


def test_copy_step_action_uses_flat_text_style():
    for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
        stylesheet = application_stylesheet(appearance)
        assert (
            f"QPushButton#copyStepButton {{ color: {tokens['text']}; "
            "background: transparent;"
        ) in stylesheet
        assert "QPushButton#copyStepButton:hover {" in stylesheet
        assert 'QPushButton#copyStepButton[keyboardFocus="true"] {' in stylesheet
        assert "QPushButton#copyStepButton:disabled {" in stylesheet
        focus_style = stylesheet.split(
            'QPushButton#copyStepButton[keyboardFocus="true"] {', 1
        )[1].split("}", 1)[0]
        hover_style = stylesheet.split(
            "QPushButton#copyStepButton:hover {", 1
        )[1].split("}", 1)[0]
        assert "border: 0;" in focus_style
        assert "text-decoration: none;" in hover_style
        assert "text-decoration: underline;" not in hover_style


def test_workflow_active_state_and_cover_selection_do_not_draw_underlines():
    stylesheet = application_stylesheet("Dark")
    assert 'QPushButton#workflowStageButton[workflowActive="true"]' in stylesheet
    assert 'QPushButton#vocabularyButton[workflowActive="true"]' in stylesheet
    assert "novelCoverRail" not in stylesheet


def test_native_palette_keeps_disabled_toolbar_labels_legible():
    for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
        palette = qt_palette(appearance)
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            assert palette.color(QPalette.Disabled, role).name().upper() == tokens[
                "disabled_text"
            ]
        assert _contrast(tokens["focus"], tokens["app"]) >= 3
        assert _contrast(tokens["focus"], tokens["surface"]) >= 3
        assert _contrast(tokens["selection_text"], tokens["selection"]) >= 4.5


def test_system_appearance_does_not_follow_the_last_app_theme(monkeypatch):
    monkeypatch.setattr(theme, "_SYSTEM_APPEARANCE_DARK", False)
    assert theme.theme_colors("System") is _LIGHT
    monkeypatch.setattr(theme, "_SYSTEM_APPEARANCE_DARK", True)
    assert theme.theme_colors("System") is _DARK
