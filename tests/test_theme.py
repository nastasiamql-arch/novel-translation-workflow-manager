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


def test_accent_and_editor_search_colors_are_neutral_grayscale():
    for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
        for role in ("accent", "focus", "primary", "primary_hover", "selection"):
            color = tokens[role]
            assert color[1:3] == color[3:5] == color[5:7], (appearance, role, color)
        assert theme.editor_colors(appearance)["find"][1:3] == (
            theme.editor_colors(appearance)["find"][3:5]
        ) == theme.editor_colors(appearance)["find"][5:7]


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
        assert "QToolButton:focus" in stylesheet
        assert "font-size: 12pt" in stylesheet


def test_copy_step_action_uses_flat_text_style():
    for appearance, tokens in (("Dark", _DARK), ("Light", _LIGHT)):
        stylesheet = application_stylesheet(appearance)
        assert (
            f"QPushButton#copyStepButton {{ color: {tokens['text']}; "
            "background: transparent;"
        ) in stylesheet
        assert "QPushButton#copyStepButton:hover {" in stylesheet
        assert "QPushButton#copyStepButton:focus {" in stylesheet
        assert "QPushButton#copyStepButton:disabled {" in stylesheet
        focus_style = stylesheet.split(
            "QPushButton#copyStepButton:focus {", 1
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
    cover_style = stylesheet.split(
        "QListWidget#novelCoverRail::item:selected {", 1
    )[1].split("}", 1)[0]
    assert "border: 0;" in cover_style
    assert "border-left" not in cover_style


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
