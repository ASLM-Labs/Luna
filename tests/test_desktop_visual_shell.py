from __future__ import annotations

from luna.desktop import (
    DARK_THEME_TOKENS,
    LUNA_DARK_PALETTE,
    LUNA_LIGHT_PALETTE,
    THEME_TOKENS,
    DesktopLayoutMode,
    desktop_layout_for_width,
)


def test_semantic_luna_palettes_are_complete_and_independently_named() -> None:
    light = LUNA_LIGHT_PALETTE.as_tokens()
    dark = LUNA_DARK_PALETTE.as_tokens()

    assert set(light) == set(dark)
    assert all(name.startswith("luna.") for name in light)
    assert light["luna.theme"] == "light"
    assert dark["luna.theme"] == "dark"
    assert light["luna.bg.primary"] != dark["luna.bg.primary"]
    assert THEME_TOKENS["luna.accent.primary"] == LUNA_LIGHT_PALETTE.accent_primary
    assert DARK_THEME_TOKENS["luna.accent.primary"] == LUNA_DARK_PALETTE.accent_primary


def test_legacy_phase16_theme_aliases_remain_locked() -> None:
    assert THEME_TOKENS["canvas"] == "#FFFFFF"
    assert THEME_TOKENS["text"] == "#171717"
    assert THEME_TOKENS["surface"] == "#F5F6F8"
    assert THEME_TOKENS["blue"] == "#2563EB"


def test_responsive_layout_collapses_inspector_then_navigation() -> None:
    wide = desktop_layout_for_width(1440)
    medium = desktop_layout_for_width(1100)
    narrow = desktop_layout_for_width(760)

    assert wide.mode is DesktopLayoutMode.WIDE
    assert wide.inspector_default_visible
    assert not wide.compact_navigation

    assert medium.mode is DesktopLayoutMode.MEDIUM
    assert not medium.inspector_default_visible
    assert not medium.compact_navigation

    assert narrow.mode is DesktopLayoutMode.NARROW
    assert not narrow.inspector_default_visible
    assert narrow.compact_navigation
    assert narrow.sidebar_width < medium.sidebar_width
