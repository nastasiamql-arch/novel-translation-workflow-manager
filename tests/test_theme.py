from novel_workflow.theme import _DARK, _LIGHT, application_stylesheet


def _luminance(color: str) -> float:
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
              for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    first, second = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (first + 0.05) / (second + 0.05)


def test_theme_text_and_status_bar_meet_readable_contrast():
    for palette in (_DARK, _LIGHT):
        assert _contrast(palette["text"], palette["app"]) >= 4.5
        assert _contrast(palette["muted"], palette["sidebar"]) >= 4.5
        assert _contrast("#FFFFFF", palette["status"]) >= 4.5


def test_theme_styles_disabled_controls_and_keyboard_focus_explicitly():
    for appearance in ("Dark", "Light"):
        stylesheet = application_stylesheet(appearance)
        assert "QToolBar#mainToolbar QToolButton:disabled" in stylesheet
        assert "QPushButton:disabled" in stylesheet
        assert "QToolButton:focus" in stylesheet
        assert "font-size: 11pt" in stylesheet
