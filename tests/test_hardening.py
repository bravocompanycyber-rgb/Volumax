"""Contrast and self-healing regression tests."""
import json
from volumax.settings import Settings
from volumax.ui.main_window import COLORS


def _lum(h):
    h = h.lstrip("#"); c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _cr(a, b):
    x, y = sorted((_lum(a), _lum(b)), reverse=True)
    return (x + 0.05) / (y + 0.05)


def test_text_contrast_wcag_aa():
    for fg in ("text", "text_dim", "link", "danger", "success", "warning", "accent_gold"):
        for bg in ("bg_dark", "bg_panel", "bg_card", "bg_hover"):
            assert _cr(COLORS[fg], COLORS[bg]) >= 4.5, (fg, bg)


def test_button_fill_contrast():
    for fill in ("accent_blue", "accent_blue_hover", "danger_fill"):
        assert _cr("#ffffff", COLORS[fill]) >= 4.5, fill
    assert _cr("#1a1a1a", COLORS["accent_gold"]) >= 4.5


def test_corrupt_settings_recovered(tmp_path):
    p = tmp_path / "settings.json"; p.write_text("{not json", encoding="utf-8")
    s = Settings(p)
    assert s.get("compression_preset") == "maximum"
    assert s.recovered_from and list(tmp_path.glob("settings.corrupt-*"))
    assert json.loads(p.read_text())  # valid file rewritten


def test_non_dict_settings_recovered(tmp_path):
    p = tmp_path / "settings.json"; p.write_text("[1,2]", encoding="utf-8")
    assert Settings(p).recovered_from


def test_selected_tab_has_visible_marker_and_contrast():
    assert _cr(COLORS["text"], COLORS["bg_card"]) >= 4.5          # selected tab text
    assert _cr(COLORS["text_dim"], COLORS["bg_panel"]) >= 4.5     # unselected tab text
    assert _cr(COLORS["accent_gold"], COLORS["bg_card"]) >= 3.0   # underline marker (UI component, 3:1)
