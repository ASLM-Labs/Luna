"""Central Luna-owned visual tokens for the desktop product shell.

The legacy Phase 16 aliases remain stable for compatibility.  New renderer code
uses the semantic ``luna.*`` palette so light and dark surfaces share one visual
contract without borrowing product assets or private tokens from another app.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class LunaPalette:
    """Semantic colors owned by Luna's desktop presentation layer."""

    name: str
    bg_primary: str
    bg_secondary: str
    bg_elevated: str
    bg_sidebar: str
    bg_inspector: str
    border_subtle: str
    border_strong: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent_primary: str
    accent_hover: str
    accent_soft: str
    state_hover: str
    state_selected: str
    state_focus: str
    state_disabled: str
    success: str
    success_soft: str
    warning: str
    warning_soft: str
    danger: str
    danger_soft: str
    shadow: str

    def as_tokens(self) -> dict[str, str]:
        """Return public semantic token names for inspection and tests."""
        return {
            "luna.theme": self.name,
            "luna.bg.primary": self.bg_primary,
            "luna.bg.secondary": self.bg_secondary,
            "luna.bg.elevated": self.bg_elevated,
            "luna.bg.sidebar": self.bg_sidebar,
            "luna.bg.inspector": self.bg_inspector,
            "luna.border.subtle": self.border_subtle,
            "luna.border.strong": self.border_strong,
            "luna.text.primary": self.text_primary,
            "luna.text.secondary": self.text_secondary,
            "luna.text.muted": self.text_muted,
            "luna.accent.primary": self.accent_primary,
            "luna.accent.hover": self.accent_hover,
            "luna.accent.soft": self.accent_soft,
            "luna.state.hover": self.state_hover,
            "luna.state.selected": self.state_selected,
            "luna.state.focus": self.state_focus,
            "luna.state.disabled": self.state_disabled,
            "luna.state.success": self.success,
            "luna.state.success_soft": self.success_soft,
            "luna.state.warning": self.warning,
            "luna.state.warning_soft": self.warning_soft,
            "luna.state.danger": self.danger,
            "luna.state.danger_soft": self.danger_soft,
            "luna.shadow": self.shadow,
        }


# Luna-owned palettes derived for this shell.  They are not official tokens from
# the Codex/OpenAI applications and intentionally use a restrained lunar-indigo
# accent to keep Luna independently branded.
LUNA_LIGHT_PALETTE: Final = LunaPalette(
    name="light",
    bg_primary="#FFFFFF",
    bg_secondary="#F7F7F5",
    bg_elevated="#FFFFFF",
    bg_sidebar="#F3F3F1",
    bg_inspector="#F8F8F6",
    border_subtle="#E7E7E3",
    border_strong="#D8D8D2",
    text_primary="#20201F",
    text_secondary="#62625E",
    text_muted="#8B8B85",
    accent_primary="#6257C8",
    accent_hover="#554AB8",
    accent_soft="#EFEDFF",
    state_hover="#EBEBE7",
    state_selected="#E5E4DF",
    state_focus="#766BE0",
    state_disabled="#B7B7B1",
    success="#26734D",
    success_soft="#E8F5ED",
    warning="#9A5B13",
    warning_soft="#FFF3DF",
    danger="#B53B3B",
    danger_soft="#FDECEC",
    shadow="#000000",
)

LUNA_DARK_PALETTE: Final = LunaPalette(
    name="dark",
    bg_primary="#1C1C1B",
    bg_secondary="#20201F",
    bg_elevated="#262624",
    bg_sidebar="#181817",
    bg_inspector="#20201F",
    border_subtle="#30302E",
    border_strong="#41413E",
    text_primary="#F1F1EE",
    text_secondary="#B7B7B1",
    text_muted="#85857F",
    accent_primary="#9B92F2",
    accent_hover="#ADA5FA",
    accent_soft="#312E4B",
    state_hover="#292927",
    state_selected="#32322F",
    state_focus="#9B92F2",
    state_disabled="#62625E",
    success="#70C397",
    success_soft="#20392C",
    warning="#E6AF65",
    warning_soft="#3B3020",
    danger="#EC8686",
    danger_soft="#442727",
    shadow="#000000",
)

# Locked Phase 16 aliases.  These values are kept so runtime verification and
# external consumers of the original theme dictionary continue to pass.
LUNA_CANVAS: Final = "#FFFFFF"
LUNA_TEXT: Final = "#171717"
LUNA_SECONDARY: Final = "#666B73"
LUNA_BORDER: Final = "#E7E9ED"
LUNA_SURFACE: Final = "#F5F6F8"
LUNA_SIDEBAR: Final = "#F1F5F9"
LUNA_BLUE: Final = "#2563EB"
LUNA_BLUE_SOFT: Final = "#EAF1FF"
LUNA_SUCCESS: Final = "#15803D"
LUNA_WARNING: Final = "#B45309"
LUNA_DANGER: Final = "#B91C1C"

BASE_FONT_FAMILY: Final = "Segoe UI"
BASE_FONT_SIZE: Final = 11
TITLE_FONT_SIZE: Final = 24
SMALL_FONT_SIZE: Final = 9
LABEL_FONT_SIZE: Final = 10

SIDEBAR_WIDTH: Final = 264
SIDEBAR_COMPACT_WIDTH: Final = 72
INSPECTOR_WIDTH: Final = 324
CONTENT_MAX_WIDTH: Final = 920
CORNER_RADIUS_HINT: Final = 12
COMPOSER_RADIUS: Final = 16
CONTROL_RADIUS: Final = 8
SPACE_UNIT: Final = 4

THEME_TOKENS: Final[dict[str, str | int]] = {
    **LUNA_LIGHT_PALETTE.as_tokens(),
    "canvas": LUNA_CANVAS,
    "text": LUNA_TEXT,
    "secondary": LUNA_SECONDARY,
    "border": LUNA_BORDER,
    "surface": LUNA_SURFACE,
    "sidebar": LUNA_SIDEBAR,
    "blue": LUNA_BLUE,
    "blue_soft": LUNA_BLUE_SOFT,
    "success": LUNA_SUCCESS,
    "warning": LUNA_WARNING,
    "danger": LUNA_DANGER,
    "font_family": BASE_FONT_FAMILY,
    "font_size": BASE_FONT_SIZE,
    "title_font_size": TITLE_FONT_SIZE,
    "sidebar_width": SIDEBAR_WIDTH,
    "sidebar_compact_width": SIDEBAR_COMPACT_WIDTH,
    "inspector_width": INSPECTOR_WIDTH,
    "content_max_width": CONTENT_MAX_WIDTH,
    "corner_radius_hint": CORNER_RADIUS_HINT,
    "composer_radius": COMPOSER_RADIUS,
    "control_radius": CONTROL_RADIUS,
    "space_unit": SPACE_UNIT,
}

DARK_THEME_TOKENS: Final[dict[str, str | int]] = {
    **LUNA_DARK_PALETTE.as_tokens(),
    "font_family": BASE_FONT_FAMILY,
    "font_size": BASE_FONT_SIZE,
    "title_font_size": TITLE_FONT_SIZE,
    "sidebar_width": SIDEBAR_WIDTH,
    "sidebar_compact_width": SIDEBAR_COMPACT_WIDTH,
    "inspector_width": INSPECTOR_WIDTH,
    "content_max_width": CONTENT_MAX_WIDTH,
    "corner_radius_hint": CORNER_RADIUS_HINT,
    "composer_radius": COMPOSER_RADIUS,
    "control_radius": CONTROL_RADIUS,
    "space_unit": SPACE_UNIT,
}
